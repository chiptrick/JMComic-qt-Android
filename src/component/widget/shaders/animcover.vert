#version 450

// 换页动画覆盖层的顶点着色器。
//
// 设计要点：**逐帧不更新任何 uniform / buffer**。
// 揭示进度由 QRhiCommandBuffer.setScissor() 表达（第二个 draw 裁到已揭示矩形），
// 所以这里只需要一个覆盖整个裁剪区的四边形 + 直通 UV。
// 每帧的 GPU 侧工作就是 2 个 draw call，没有任何上传。

layout(location = 0) in vec2 aPos;   // NDC，裁剪区 -1..1
layout(location = 1) in vec2 aTex;   // 0..1

layout(location = 0) out vec2 vTex;

void main()
{
    vTex = aTex;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
