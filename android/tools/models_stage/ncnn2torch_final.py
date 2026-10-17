#!/usr/bin/env python3
"""ncnn param+bin -> torch state_dict 最终版
格式（经 ncnn 源码 + 字节账双重确认）:
  weight load: [4B tag 0x01306B47][fp16 数据, alignSize(2*ws,4)]
  bias   load: [fp32 数据, 4*out 字节, 无 tag]
映射: Convolution->Conv2d [oc,ic,kh,kw]; Deconvolution->ConvTranspose2d 需 permute(1,0,2,3);
      InnerProduct->1x1 Conv2d [oc,ic]; PReLU->[n]
"""
import struct, sys
import numpy as np
import torch

TAG_FP16 = 0x01306B47

def parse_param(path):
    layers = []
    with open(path) as f:
        lines = f.read().split('\n')
    for ln in lines[2:]:
        ln = ln.rstrip()
        if not ln: continue
        parts = ln.split()
        ltype, name = parts[0], parts[1]
        d = {}
        rest = parts[2:]
        nb = int(rest[0]); nt = int(rest[1])
        rest = rest[2+nb+nt:]
        for tok in rest:
            if '=' in tok:
                k, v = tok.split('=', 1)
                try: d[int(k)] = v
                except ValueError: pass
        layers.append({'type': ltype, 'name': name, 'dict': d})
    return layers

def read_bin(param_layers, bin_path):
    raw = open(bin_path, 'rb').read()
    off = 0
    out = {}
    for L in param_layers:
        d = L['dict']; t = L['type']
        if t in ('Convolution', 'Deconvolution'):
            ws = int(d.get(6, 0)); no = int(d.get(0, 0)); bias = int(d.get(5, 0))
            kw = int(d.get(1, 1)); kh = int(d.get(11, kw))
        elif t == 'InnerProduct':
            ws = int(d.get(2, 0)); no = int(d.get(0, 0)); bias = int(d.get(1, 0)); kw = kh = 1
        elif t == 'PReLU':
            ws = int(d.get(0, 0)); no = ws; bias = 0; kw = kh = 1
        else:
            continue
        if ws == 0: continue
        # weight: tag + fp16 aligned
        tag = struct.unpack('<I', raw[off:off+4])[0]
        assert tag == TAG_FP16, f"{L['name']}: bad tag {hex(tag)} at {off}"
        woff = off + 4
        walign = (ws * 2 + 3) & ~3
        w = np.frombuffer(raw, dtype='<f2', count=ws, offset=woff).astype(np.float32)
        off = woff + walign
        b = None
        if bias:
            b = np.frombuffer(raw, dtype='<f4', count=no, offset=off).astype(np.float32)
            off += no * 4
        out[L['name']] = {'w': w, 'b': b, 'ws': ws, 'no': no, 'type': t, 'kw': kw, 'kh': kh}
    assert off == len(raw), f"consumed {off} != file {len(raw)}"
    return out

# ncnn 层名 -> torch state_dict key
WEIGHT_MAP = [
    ('convrelu_0',     'unet1.conv1.conv.0'),
    ('convrelu_1',     'unet1.conv1.conv.2'),
    ('convrelu_2',     'unet1.conv1_down'),
    ('convrelu_3',     'unet1.conv2.conv.0'),
    ('convrelu_4',     'unet1.conv2.conv.2'),
    ('convrelu_5',     'unet1.conv2.seblock.conv1'),
    ('convsigmoid_21', 'unet1.conv2.seblock.conv2'),
    ('deconvrelu_0',   'unet1.conv2_up'),
    ('convrelu_6',     'unet1.conv3'),
    ('deconv_48',      'unet1.conv_bottom'),
    ('convrelu_7',     'unet2.conv1.conv.0'),
    ('convrelu_8',     'unet2.conv1.conv.2'),
    ('convrelu_9',     'unet2.conv1_down'),
    ('convrelu_10',    'unet2.conv2.conv.0'),
    ('convrelu_11',    'unet2.conv2.conv.2'),
    ('convrelu_12',    'unet2.conv2.seblock.conv1'),
    ('convsigmoid_22', 'unet2.conv2.seblock.conv2'),
    ('convrelu_13',    'unet2.conv2_down'),
    ('convrelu_14',    'unet2.conv3.conv.0'),
    ('convrelu_15',    'unet2.conv3.conv.2'),
    ('convrelu_16',    'unet2.conv3.seblock.conv1'),
    ('convsigmoid_23', 'unet2.conv3.seblock.conv2'),
    ('deconvrelu_1',   'unet2.conv3_up'),
    ('convrelu_17',    'unet2.conv4.conv.0'),
    ('convrelu_18',    'unet2.conv4.conv.2'),
    ('convrelu_19',    'unet2.conv4.seblock.conv1'),
    ('convsigmoid_24', 'unet2.conv4.seblock.conv2'),
    ('deconvrelu_2',   'unet2.conv4_up'),
    ('convrelu_20',    'unet2.conv5'),
    ('conv_46',        'unet2.conv_bottom'),
]

def build_state_dict(layers_data, scale):
    sd = {}
    for ncnn_name, torch_key in WEIGHT_MAP:
        rec = layers_data[ncnn_name]
        w = rec['w']; no = rec['no']; ws = rec['ws']
        kw, kh = rec['kw'], rec['kh']
        if rec['type'] == 'Convolution':
            ic = ws // no // (kw * kh)
            wt = torch.from_numpy(w.reshape(no, ic, kh, kw).copy())
        elif rec['type'] == 'InnerProduct':
            ic = ws // no
            wt = torch.from_numpy(w.reshape(no, ic, 1, 1).copy())
        elif rec['type'] == 'Deconvolution':
            ic = ws // no // (kw * kh)
            # ncnn [no, ni, kh, kw] -> torch [ni, no, kh, kw]
            wt = torch.from_numpy(np.ascontiguousarray(w.reshape(no, ic, kh, kw).transpose(1, 0, 2, 3)))
        else:
            raise ValueError(rec['type'])
        sd[torch_key + '.weight'] = wt
        if rec['b'] is not None:
            sd[torch_key + '.bias'] = torch.from_numpy(rec['b'].copy())
    return sd

def main(param_path, bin_path, out_path, scale):
    layers = parse_param(param_path)
    data = read_bin(layers, bin_path)
    print(f"parsed {len(data)} weighted layers, bin fully consumed")
    sd = build_state_dict(data, scale)
    torch.save(sd, out_path)
    print(f"saved {out_path}: {len(sd)} tensors")
    # 打印统计
    for k in list(sd)[:4]:
        print(f"  {k}: {tuple(sd[k].shape)} std={sd[k].std():.4f}")

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
