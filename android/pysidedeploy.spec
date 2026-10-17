[app]
title = JMComic
project_dir = .
input_file = main.py
project_file =
exec_directory =

[python]
python_path =
android_packages = buildozer,Cython

[qt]
modules = Core,Gui,Widgets,Network,Svg,Xml,Sql,OpenGL,OpenGLWidgets
plugins =

[android]
wheel_pyside = wheels/pyside6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl
wheel_shiboken = wheels/shiboken6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl
plugins =

[buildozer]
mode = debug
recipe_dir =
jars_dir =
ndk_path =
sdk_path =
arch = aarch64