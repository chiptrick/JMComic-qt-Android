import torch
from torch import nn as nn

def default_init_weights(module, scale=1, bias_fill=0, **kwargs):
    if isinstance(module, (list, tuple)):
        for m in module:
            default_init_weights(m, scale, bias_fill, **kwargs)
        return
    for m in module.modules():
        if isinstance(m, nn.Conv2d):
            nn.init.kaiming_normal_(m.weight, a=0, mode='fan_in')
            m.weight.data *= scale
            if m.bias is not None:
                m.bias.data.fill_(bias_fill)
        elif isinstance(m, nn.Linear):
            nn.init.kaiming_normal_(m.weight, a=0, mode='fan_in')
            m.weight.data *= scale
            if m.bias is not None:
                m.bias.data.fill_(bias_fill)

def make_layer(basic_block, num_blocks, **kwarg):
    layers = []
    for _ in range(num_blocks):
        layers.append(basic_block(**kwarg))
    return nn.Sequential(*layers)

def pixel_unshuffle(x, h2, w2, factor=2):
    b, c, h, w = x.shape
    return x.view(b, c, h // factor, factor, w // factor, factor).permute(0, 1, 3, 5, 2, 4).reshape(b, c * factor * factor, h // factor, w // factor)
