#version 450

// 换页动画覆盖层的片元着色器：直通采样。
// binding 0 对应 QRhiShaderResourceBindings 里的第 0 个
// combinedImageSampler 绑定（纹理 + 采样器）。

layout(location = 0) in vec2 vTex;
layout(location = 0) out vec4 fragColor;

layout(binding = 0) uniform sampler2D uTex;

void main()
{
    fragColor = texture(uTex, vTex);
}
