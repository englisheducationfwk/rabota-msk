# Ярлык «Работа MSK» на рабочем столе.
# Тонкость: старый COM WshShell не переваривает кириллицу в путях на этой
# системе, поэтому ярлык рождается в TEMP с ASCII-именами (pythonw + panel.py
# — всё ASCII), а затем переезжает на рабочий стол с русским именем через
# обычный Move (он юникодный и кушает всё).
$ErrorActionPreference = 'Stop'

$py = 'C:\Users\Admin\AppData\Local\Programs\Python\Python312\pythonw.exe'
$args_ = '"panel\panel.py"'
$workdir = 'C:\Users\Admin\Desktop\school\rabota-msk'
$icon = Join-Path $workdir 'docs\msk.ico'

if (-not (Test-Path -LiteralPath $py)) { throw "нет pythonw: $py" }
if (-not (Test-Path -LiteralPath $icon)) { throw "нет иконки: $icon" }

$tmp = Join-Path $env:TEMP 'msk_shortcut.lnk'
if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($tmp)
$lnk.TargetPath = $py
$lnk.Arguments = $args_
$lnk.WorkingDirectory = $workdir
$lnk.IconLocation = $icon
$lnk.Description = 'Rabota MSK - vklyuchit/vyklyuchit sbor vakansiy'
$lnk.Save()
if (-not (Test-Path -LiteralPath $tmp)) { throw 'ярлык не сохранился' }

# «Работа MSK.lnk» собираем из кодов, чтобы не зависеть от кодировки файла
$name = [char]0x0420 + [char]0x0430 + [char]0x0431 + [char]0x043E +
        [char]0x0442 + [char]0x0430 + ' MSK.lnk'
$final = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
if (Test-Path -LiteralPath $final) { Remove-Item -LiteralPath $final -Force }
[IO.File]::Move($tmp, $final)
Write-Host 'OK'
Write-Host ([IO.File]::Exists($final))
