# 给 android/tools 下的 .ps1 补 UTF-8 BOM
#
# 为什么需要：Windows PowerShell 5.1 在没有 BOM 时按系统 ANSI(中文机器上是 GBK)读脚本，
# 脚本里的中文会变成乱码并导致解析错误(报 "表达式或语句中包含意外的标记")。
# write/edit 类工具保存的都是不带 BOM 的 UTF-8，所以每次改完 .ps1 都要跑一次本脚本。
#
# 用法: powershell -File android/tools/fix_ps_bom.ps1
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$count = 0
Get-ChildItem -Path $dir -Filter *.ps1 -File | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($_.FullName, $text, (New-Object System.Text.UTF8Encoding($true)))
    Write-Host ("BOM ok: " + $_.Name)
    $count++
}
Write-Host ("共 $count 个 .ps1")
