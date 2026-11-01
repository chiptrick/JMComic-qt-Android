# 返回方向 bug：根因与修复（2026-10-31）

## 1. 现象

按返回（面包屑「返回」或系统返回键）时，页面按**前进方向**播放：新页从右侧滑入、
旧页向左移出；预期应是旧页向右移出、上一页从左侧滑入。

性能测试中 84+ 次转场 `dir` 全是 `fwd`，由此定位。

## 2. 根因

方向判断在 `AnimationStackWidget.SwitchWidgetByIndex()` 里，靠**当前页与目标页在
`subStackList` 中的下标**比较：

```python
oldIndex = subStackList.index(self.currentIndex())   # 当前页位置
newIndex = subStackList.index(index)                 # 目标页位置
animationType = LeftToRight if oldIndex <= newIndex else RightToLeft
```

而 `MainView.SwitchWidgetLast()` 为了不让面包屑残留已退掉的层级，**先裁栈、再切页**：

```python
target = subStackList[subIndex - 1]      # 上一页
keep = subStackList[:subIndex]           # 丢掉当前页及之后
self.ClearTabBar()                       # 会清空 subStackList
self.subStackList = keep                 # 栈里已经没有"当前页"了
self.UpdateTabBar()
self.SwitchWidgetByIndex(target)         # ← 此时才判断方向
```

于是 `currentIndex()` 不在 `subStackList` 里，`oldIndex` 落到兜底值 **0**；
目标页是 `keep` 的第 0 项，`newIndex` 也是 **0** → `0 <= 0` → **恒为 LeftToRight**。

这是**状态变更顺序**问题，不是坐标/角度计算问题：
方向所依赖的"当前页在栈中的位置"在判断之前就被删掉了。

同类问题也存在于 `SwitchWidgetAndClear()`（先把栈重置成 `[index]` 再切），
但那条路径是"点导航重建栈"，按前进播放是符合预期的，不在本次修复范围。

## 3. 最小改动

**原则：不改裁栈顺序**（`UpdateTabBar()` 必须在动画前完成，否则面包屑重排会把
首帧打断，见 `main_view.py` 里 2026-10 的注释），只把"方向"从隐式推导改成显式传参。

1. `AnimationStackWidget.SwitchWidgetByIndex(index, direction=None, **kwargs)`：
   `direction` 非空时直接用，否则保持原来的下标推导（其他调用点零影响）。
2. `MainView.SwitchWidgetByIndex(index, direction=None, **kwargs)`：
   把 `direction` 透传给 `_SwitchWidgetNow()`（抽屉延迟路径也要带上）。
3. `_SwitchWidgetNow(index, direction=None, **kwargs)`：
   `self.subStackWidget.SwitchWidgetByIndex(index, direction, **kwargs)`。
4. `SwitchWidgetLast()` 在裁栈之后调用：
   `self.SwitchWidgetByIndex(target, AnimationEnum.RightToLeft)`。

总计 4 处、约 15 行；`direction` 是显式形参，不会被塞进 `switchArg` 传给
`SwitchCurrent(**kwargs)`（有测试守着）。

## 4. 验证

### 4.1 宿主回归（`android/tools/host_test_switch_direction.py`）

```
[1] 完整栈上的方向推导：前进 / 面包屑后退        ok（LeftToRight / RightToLeft）
[2] 返回路径：先裁栈 + 显式方向                  ok（RightToLeft，switchArg 无 direction）
[3] 反例守卫：裁栈后不传方向会退化成前进          ok（复现旧 bug 根因）
[4] 源码守卫：SwitchWidgetLast 必须传 RightToLeft ok
ALL PASS（exit 0）
```

> 注：该测试进程用 `os._exit()` 收尾——PySide6 在解释器 finalize 阶段回收
> QRigWidget/QWidget 时偶发 `bool_dealloc ... refcount error`，断言跑完后崩溃会
> 污染退出码；直接退出可避开（其他宿主测试没有大量创建 QRhiWidget，不受影响）。

### 4.2 真机（V2463A / Android 17，0.87 + 临时 DIRCHECK 日志）

```
[DIRCHECK] 0->11  direction=LeftToRight explicit=False   # 菜单进设置：推导，前进
[DIRCHECK] 11->0  direction=RightToLeft explicit=True    # 返回：显式，后退
```

修复前第二条会是 `LeftToRight explicit=False`。取证日志已删除，发布包不含。

### 4.3 未覆盖项

像素级的"旧页向右移出"需要慢动作抓帧（250ms 只有 ~28 帧，普通录屏抓不稳）。
方向枚举已由宿主测试 + 真机日志双重确认，`_OffsetsFor(type=2)` 的几何由
`host_test_gpu_layer.py` 的"后退 50%/100%"用例覆盖；如需视觉复核，按
`mobile_vulkan_migration.md` §7.4 的慢动作取证法做一次即可。
