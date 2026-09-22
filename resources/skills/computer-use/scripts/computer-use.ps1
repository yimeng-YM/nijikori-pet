[CmdletBinding()]
param(
    [ValidateSet('Check','Validate','Windows','Focus','Observe','Click','DoubleClick','Move','Drag','Scroll','Type','Key','Steps')]
    [string]$Action,
    [long]$WindowId = 0,
    [string]$Window,
    [string]$Observation,
    [int]$X = -1, [int]$Y = -1, [int]$ToX = -1, [int]$ToY = -1,
    [ValidateSet('Left','Right')][string]$Button = 'Left',
    [ValidateRange(-10,10)][int]$Amount = -3,
    [string]$Text, [string]$TextFile, [string]$Keys,
    [string]$ArgsFile, [string]$Steps, [string]$StepsFile,
    [int]$SnapshotDelayMs = 0,
    [ValidateSet('append','replace')][string]$Mode = 'append',
    [int]$PetPid = 0,
    [switch]$NoSnapshot,
    [string]$SaveSnapshot
)
$ErrorActionPreference = 'Stop'
$script:ActionPerformed = $false
$StepObjects = $null
try {
    if ($ArgsFile) {
        $cfg = [IO.File]::ReadAllText($ArgsFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
        foreach ($prop in $cfg.PSObject.Properties) {
            switch ($prop.Name) {
                'action'            { $Action = [string]$prop.Value }
                'window'            { $Window = [string]$prop.Value }
                'window_id'         { $WindowId = [long]$prop.Value }
                'observation'       { $Observation = [string]$prop.Value }
                'x'                 { $X = [int]$prop.Value }
                'y'                 { $Y = [int]$prop.Value }
                'to_x'              { $ToX = [int]$prop.Value }
                'to_y'              { $ToY = [int]$prop.Value }
                'amount'            { $Amount = [int]$prop.Value }
                'button'            { $Button = [string]$prop.Value }
                'text'              { $Text = [string]$prop.Value }
                'text_file'         { $TextFile = [string]$prop.Value }
                'keys'              { $Keys = [string]$prop.Value }
                'steps'             { $StepObjects = @($prop.Value | ForEach-Object { $_ }) }
                'snapshot_delay_ms' { $SnapshotDelayMs = [int]$prop.Value }
                'mode'              { $Mode = [string]$prop.Value }
                'pet_pid'           { $PetPid = [int]$prop.Value }
                'no_snapshot'       { $NoSnapshot = [bool]$prop.Value }
                'save_snapshot'     { $SaveSnapshot = [string]$prop.Value }
            }
        }
    }
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    if (-not ('NijiComputer' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'native.cs') }
    # Steps take the same names as single actions (double_click included) plus sleep.
    $script:StepAliases = @{
        'click'='click'; 'doubleclick'='doubleclick'; 'double_click'='doubleclick'
        'double-click'='doubleclick'; 'dblclick'='doubleclick'; 'dbl_click'='doubleclick'
        'move'='move'; 'drag'='drag'; 'scroll'='scroll'
        'type'='type'; 'input'='type'; 'key'='key'; 'keys'='key'; 'press'='key'
        'sleep'='sleep'; 'wait'='sleep'
    }
    # Friendly app names -> process names, so a keyword keeps working after the
    # window title changes (for example PowerPoint straight after Save As).
    $script:ProcessAliases = @{
        'powerpoint'='powerpnt'; 'ppt'='powerpnt'; 'powerpnt'='powerpnt'; '演示文稿'='powerpnt'
        'word'='winword'; 'winword'='winword'; '文档'='winword'
        'excel'='excel'; '表格'='excel'
        'wps演示'='wpp'; 'wps文字'='wps'; 'wps表格'='et'
        'notepad'='notepad'; '记事本'='notepad'
        'explorer'='explorer'; '文件资源管理器'='explorer'; '资源管理器'='explorer'
        'chrome'='chrome'; '谷歌浏览器'='chrome'; 'edge'='msedge'; 'microsoft edge'='msedge'
        'firefox'='firefox'; 'vscode'='code'; 'vs code'='code'
        '微信'='wechat'; 'wechat'='wechat'; 'qq'='qq'; 'pycharm'='pycharm'
        '终端'='windowsterminal'; 'terminal'='windowsterminal'
    }
    function Normalize-Text([string]$value) {
        if ([string]::IsNullOrEmpty($value)) { return $value }
        # Models often send a literal backslash-n; treat it as a real line break.
        $value = $value -replace '\\r\\n', "`n"
        $value = $value -replace '\\n', "`n"
        $value = $value -replace '\\t', "`t"
        return $value
    }
    function Get-NormalizedSteps {
        $raw = @()
        if ($StepObjects) { $raw = @($StepObjects | ForEach-Object { $_ }) }
        elseif ($StepsFile) { $raw = @(([IO.File]::ReadAllText($StepsFile, [Text.Encoding]::UTF8) | ConvertFrom-Json) | ForEach-Object { $_ }) }
        elseif ($Steps) { $raw = @(($Steps | ConvertFrom-Json) | ForEach-Object { $_ }) }
        $list = @()
        foreach ($step in $raw) {
            if ($null -eq $step) { continue }
            $rawAct = ([string]$step.action).Trim().ToLower()
            if ([string]::IsNullOrEmpty($rawAct)) { throw 'step.action is required' }
            $act = $script:StepAliases[$rawAct]
            if (-not $act) {
                $allowed = @('click','doubleclick','move','drag','scroll','type','key','sleep') -join ' / '
                throw ('Unsupported step action: ' + $rawAct + '；可用动作：' + $allowed)
            }
            $step.action = $act
            $list += $step
        }
        return $list
    }
    if ($Action -eq 'Validate') {
        # Dry run: normalise a payload and report it without injecting any input.
        @{status='success'; action='validate'; mode=$Mode; text=(Normalize-Text $Text)
          keys=$Keys; window=$Window; steps=@(Get-NormalizedSteps)} |
            ConvertTo-Json -Depth 6 -Compress
        exit 0
    }
    if ($Action -eq 'Check') {
        $size = [NijiComputer]::InputSize()
        $expected = if ([IntPtr]::Size -eq 8) { 40 } else { 28 }
        if ($size -ne $expected) { throw "Invalid Windows INPUT layout: $size" }
        $screen = [NijiComputer]::VirtualScreen()
        @{status='success'; input_size=$size; powershell=$PSVersionTable.PSVersion.ToString()
          interactive=[Environment]::UserInteractive; dpi_awareness=[NijiComputer]::MakeDpiAware()
          virtual_screen=@{left=$screen.Left; top=$screen.Top
                           width=$screen.Right - $screen.Left; height=$screen.Bottom - $screen.Top}} | ConvertTo-Json -Compress
        exit 0
    }
    # PER_MONITOR_AWARE_V2 keeps screen coordinates physical even when monitors
    # use different scaling factors.
    $dpiMode = [NijiComputer]::MakeDpiAware()
    [NijiComputer]::CheckStop()
    if ($Action -eq 'Windows') {
        @{status='success'; windows=@([NijiComputer]::Windows())} | ConvertTo-Json -Depth 5 -Compress
        exit 0
    }
    $cacheDir = Join-Path ([IO.Path]::GetTempPath()) 'NijiKori-computer-use'
    [void][IO.Directory]::CreateDirectory($cacheDir)
    $script:CacheDir = $cacheDir
    $script:PetPid = $PetPid
    # One snapshot token stays valid for this long and for as many steps as the
    # caller needs: it is no longer consumed by the first input that uses it.
    $script:ObservationTtlSeconds = 600

    function Get-ImagePoint($snapshot, [int]$px, [int]$py) {
        if ($px -lt 0 -or $py -lt 0) {
            throw '这个动作需要图片坐标 x/y：请先 observe/focus 拿一张快照，再按图片像素给出 x,y'
        }
        if ($px -ge $snapshot.image_width -or $py -ge $snapshot.image_height) {
            throw ('Coordinates must be inside the observed image：坐标 (' + $px + ',' + $py + ') 超出快照 ' + $snapshot.image_width + 'x' + $snapshot.image_height + '，请按 image_width/image_height 重新量')
        }
        return @([int]($snapshot.left + [Math]::Floor($px * $snapshot.width / $snapshot.image_width)),
                 [int]($snapshot.top + [Math]::Floor($py * $snapshot.height / $snapshot.image_height)))
    }

    function Get-WindowMemory {
        $mem = @{}
        $path = Join-Path $script:CacheDir 'window-memory.json'
        if (-not [IO.File]::Exists($path)) { return $mem }
        try {
            $raw = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
            foreach ($prop in $raw.PSObject.Properties) {
                $mem[$prop.Name] = @{ id = [long]$prop.Value.id
                                      process = [string]$prop.Value.process
                                      title = [string]$prop.Value.title }
            }
        } catch { $mem = @{} }
        return $mem
    }

    function Set-WindowMemory([string]$keyword, $window) {
        if ([string]::IsNullOrWhiteSpace($keyword) -or -not $window) { return }
        try {
            $mem = Get-WindowMemory
            $mem[$keyword.Trim().ToLower()] = @{ id = [long]$window.id
                                                 process = [string]$window.process
                                                 title = [string]$window.title }
            [IO.File]::WriteAllText((Join-Path $script:CacheDir 'window-memory.json'),
                                    ($mem | ConvertTo-Json -Depth 4 -Compress), [Text.Encoding]::UTF8)
        } catch { }
    }

    function Find-TargetWindow([string]$keyword) {
        if ([string]::IsNullOrWhiteSpace($keyword)) { return $null }
        $kw = $keyword.Trim().ToLower()
        $all = @([NijiComputer]::Windows())
        if ($kw -eq 'active' -or $kw -eq 'current' -or $kw -eq '前景' -or $kw -eq '前台' -or $kw -eq '当前') {
            $fg = [long][NijiComputer]::Foreground()
            $fgHit = $all | Where-Object { $_.id -eq $fg } | Select-Object -First 1
            return $fgHit
        }
        $hit = $all | Where-Object { $_.title -and $_.title.ToLower() -eq $kw } | Select-Object -First 1
        if (-not $hit) { $hit = $all | Where-Object { $_.process -and $_.process.ToLower() -eq $kw } | Select-Object -First 1 }
        if (-not $hit -and $script:ProcessAliases.ContainsKey($kw)) {
            # Friendly name ("PowerPoint") -> process name ("powerpnt").
            $proc = [string]$script:ProcessAliases[$kw]
            $hit = $all | Where-Object { $_.process -and $_.process.ToLower() -eq $proc } | Select-Object -First 1
        }
        if (-not $hit) { $hit = $all | Where-Object { $_.title -and $_.title.ToLower().Contains($kw) } | Select-Object -First 1 }
        if (-not $hit) { $hit = $all | Where-Object { $_.process -and $_.process.ToLower().Contains($kw) } | Select-Object -First 1 }
        if (-not $hit) {
            # The same window as last time under this keyword, even though its
            # title changed (Save As, new document); then any window of its process.
            $mem = Get-WindowMemory
            if ($mem.ContainsKey($kw)) {
                $entry = $mem[$kw]
                $hit = $all | Where-Object { $_.id -eq [long]$entry.id } | Select-Object -First 1
                if (-not $hit -and $entry.process) {
                    $hit = $all | Where-Object { $_.process -and $_.process.ToLower() -eq ([string]$entry.process).ToLower() } | Select-Object -First 1
                }
            }
        }
        if ($hit) { Set-WindowMemory $kw $hit }
        return $hit
    }

    function Set-TargetForeground($target) {
        if ([NijiComputer]::Foreground() -ne $target.ToInt64()) {
            if ([NijiComputer]::IsIconic($target)) {
                [void][NijiComputer]::ShowWindow($target, 9)
                Start-Sleep -Milliseconds 250
            }
            # A plain SetForegroundWindow is refused while another app (often the
            # pet's own chat window) owns the foreground, so ForceForeground also
            # attaches the input queues before retrying.
            [void][NijiComputer]::ForceForeground($target)
            Start-Sleep -Milliseconds 120
        }
        [NijiComputer]::Guard($target)
    }

    function Get-ObservationState([string]$token) {
        if ($token -notmatch '^[a-f0-9]{32}$') { throw 'A valid observation token is required' }
        $statePath = Join-Path $script:CacheDir ($token + '.json')
        if (-not [IO.File]::Exists($statePath)) {
            throw ('快照 ' + $token.Substring(0, 8) + '… 已失效：临时状态已被清理，请重新 observe/focus 拿一张新快照。observation token expired, observe again')
        }
        try { $state = [IO.File]::ReadAllText($statePath, [Text.Encoding]::UTF8) | ConvertFrom-Json }
        catch { throw '快照状态文件损坏：请重新 observe/focus。observation token unreadable, observe again' }
        $age = ([DateTime]::UtcNow - [DateTime]::Parse([string]$state.created_utc).ToUniversalTime()).TotalSeconds
        if ($age -gt $script:ObservationTtlSeconds) {
            throw ('快照已过期（' + [int]$age + ' 秒前拍的，上限 ' + $script:ObservationTtlSeconds + ' 秒）：请重新 observe/focus。observation token expired, observe again')
        }
        return $state
    }

    function New-Snapshot($target) {
        # $target = IntPtr::Zero means "the whole virtual desktop" (screen mode):
        # other windows are expected to be on top, so this is a plain screen grab.
        $wholeScreen = ($target -eq [IntPtr]::Zero)
        if (-not $wholeScreen) {
            [NijiComputer]::Guard($target)
            if ([NijiComputer]::IsIconic($target)) {
                [void][NijiComputer]::ShowWindow($target, 9)
                Start-Sleep -Milliseconds 300
            }
            $rect = [NijiComputer]::Bounds($target)
        } else {
            $rect = [NijiComputer]::VirtualScreen()
        }
        $width = $rect.Right - $rect.Left
        $height = $rect.Bottom - $rect.Top
        if ($width -le 0 -or $height -le 0) { throw 'Target has no visible size' }
        $left = $rect.Left
        $top = $rect.Top
        $method = 'printwindow'
        if ($wholeScreen) { $method = 'screen' }
        # A DPI-unaware (legacy) window is rendered by PrintWindow at its own
        # logical size instead of the physical window rect, which would break
        # coordinate mapping. Scale the render box by the window DPI so the
        # image matches what the app thinks its size is; Get-ImagePoint then
        # multiplies back to physical screen coordinates.
        $renderW = $width
        $renderH = $height
        if (-not $wholeScreen) {
            $sysDpi = [NijiComputer]::SystemDpi()
            if ($sysDpi -gt 96 -and [NijiComputer]::IsDpiUnaware($target)) {
                $renderW = [Math]::Max(1, [int][Math]::Round($width * 96.0 / $sysDpi))
                $renderH = [Math]::Max(1, [int][Math]::Round($height * 96.0 / $sysDpi))
            }
        }
        $bitmap = $null
        try {
            if ($wholeScreen) { throw 'screen grab' }
            # Off-screen render: other windows (and the always-on-top pet) cannot occlude it.
            $bgra = [NijiComputer]::CaptureBgra($target, $renderW, $renderH)
            if ([NijiComputer]::IsFlatPixels($bgra)) { throw 'flat PrintWindow render' }
            $bitmap = New-Object Drawing.Bitmap($renderW, $renderH, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
            $box = New-Object Drawing.Rectangle(0, 0, $renderW, $renderH)
            $locked = $bitmap.LockBits($box, [Drawing.Imaging.ImageLockMode]::WriteOnly, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
            [Runtime.InteropServices.Marshal]::Copy($bgra, 0, $locked.Scan0, $bgra.Length)
            $bitmap.UnlockBits($locked)
        } catch {
            if ($bitmap) { $bitmap.Dispose(); $bitmap = $null }
            $desktop = [Windows.Forms.SystemInformation]::VirtualScreen
            $left = [Math]::Max($rect.Left, $desktop.Left)
            $top = [Math]::Max($rect.Top, $desktop.Top)
            $width = [Math]::Min($rect.Right, $desktop.Right) - $left
            $height = [Math]::Min($rect.Bottom, $desktop.Bottom) - $top
            if ($width -le 0 -or $height -le 0) { throw 'Target is not visible on the desktop' }
            $method = 'screen'
            $renderW = $width
            $renderH = $height
            $bitmap = New-Object Drawing.Bitmap($width, $height)
            $grab = [Drawing.Graphics]::FromImage($bitmap)
            try { $grab.CopyFromScreen($left, $top, 0, 0, $bitmap.Size) } finally { $grab.Dispose() }
        }
        $ratio = [Math]::Min(1.0, 1280.0 / [Math]::Max($renderW, $renderH))
        $iw = [Math]::Max(1, [int][Math]::Round($renderW * $ratio))
        $ih = [Math]::Max(1, [int][Math]::Round($renderH * $ratio))
        $token = [Guid]::NewGuid().ToString('N')
        $imagePath = Join-Path $script:CacheDir ($token + '.png')
        $scaled = $null; $graphics = $null; $resizer = $null
        try {
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            $scaled = New-Object Drawing.Bitmap($iw, $ih)
            $resizer = [Drawing.Graphics]::FromImage($scaled)
            $resizer.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $resizer.DrawImage($bitmap, 0, 0, $iw, $ih)
            $scaled.Save($imagePath, [Drawing.Imaging.ImageFormat]::Png)
        } finally {
            if ($resizer) { $resizer.Dispose() }
            if ($scaled) { $scaled.Dispose() }
            if ($graphics) { $graphics.Dispose() }
            if ($bitmap) { $bitmap.Dispose() }
        }
        if (-not $wholeScreen) {
            [NijiComputer]::Guard($target)
            if (([NijiComputer]::Bounds($target) | ConvertTo-Json -Compress) -ne ($rect | ConvertTo-Json -Compress)) {
                throw 'Window moved during screenshot; observe again'
            }
        }
        if ($wholeScreen) {
            $snapWindowId = 0
            $snapProcessId = 0
        } else {
            $snapWindowId = $target.ToInt64()
            $snapProcessId = [NijiComputer]::ProcessId($target)
        }
        $snap = [ordered]@{
            status='success'; action_performed=$script:ActionPerformed
            observation=$token; screenshot=$imagePath
            window_id=$snapWindowId
            process_id=$snapProcessId
            whole_screen=$wholeScreen
            created_utc=[DateTime]::UtcNow.ToString('o'); bounds=$rect
            left=$left; top=$top; width=$width; height=$height
            image_width=$iw; image_height=$ih; method=$method
        }
        [IO.File]::WriteAllText((Join-Path $script:CacheDir ($token + '.json')),
                                ($snap | ConvertTo-Json -Depth 5 -Compress), [Text.Encoding]::UTF8)
        return $snap
    }

    function Assert-NotPetCovered([string]$what, [int]$x, [int]$y) {
        if ($script:PetPid -le 0) { return }
        if ([NijiComputer]::ProcessIdAtPoint($x, $y) -eq $script:PetPid) {
            throw ('PET_BLOCKS:' + $what + ' at ' + $x + ',' + $y)
        }
    }

    function Invoke-InputStep($target, $state, [string]$act, [int]$px, [int]$py, [int]$tx, [int]$ty,
                              [string]$btn, [int]$amt, [string]$txt, [string]$keys, [string]$mode = 'append') {
        # Screen mode (window_id 0): no window to focus and no occlusion guard —
        # the click simply lands wherever the point is on the desktop.
        $wholeScreen = ($target -eq [IntPtr]::Zero)
        if ($wholeScreen) {
            [NijiComputer]::CheckStop()
        } else {
            Set-TargetForeground $target
            if ($state -and (([NijiComputer]::Bounds($target) | ConvertTo-Json -Compress) -ne ($state.bounds | ConvertTo-Json -Compress))) {
                throw 'Window moved or resized; observe again（窗口已移动或缩放，请重新 observe 再操作）'
            }
        }
        # Keyboard actions carry no coordinates: they go to the focused window.
        if ($act -eq 'Type') {
            if ([string]::IsNullOrEmpty($txt)) { throw 'Text or TextFile is required' }
            if ($mode -eq 'replace') {
                if ($wholeScreen) { [NijiComputer]::ChordFree('CTRL,A') } else { [NijiComputer]::Chord($target, 'CTRL,A') }
                Start-Sleep -Milliseconds 80
            }
            if ($wholeScreen) { [NijiComputer]::TypeTextFree($txt) } else { [NijiComputer]::TypeText($target, $txt) }
            return
        }
        if ($act -eq 'Key') {
            if (-not $keys) { throw 'Keys is required' }
            if ($wholeScreen) { [NijiComputer]::ChordFree($keys) } else { [NijiComputer]::Chord($target, $keys) }
            return
        }
        $point = Get-ImagePoint $state $px $py
        # The pet is always on top: report it distinctly so the caller can hide
        # the pet and retry instead of failing with a generic "covered" error.
        Assert-NotPetCovered $act $point[0] $point[1]
        if (-not $wholeScreen) { [NijiComputer]::TargetPoint($target, $point[0], $point[1]) }
        if ($act -eq 'Drag') {
            $end = Get-ImagePoint $state $tx $ty
            if (-not $wholeScreen) { [NijiComputer]::TargetPoint($target, $end[0], $end[1]) }
        }
        if (-not [NijiComputer]::SetCursorPos($point[0], $point[1])) { throw 'Cannot move cursor' }
        if (-not $wholeScreen) { [NijiComputer]::TargetPoint($target, $point[0], $point[1]) }
        if ($act -in @('Click','DoubleClick','Drag')) {
            $down = if ($btn -eq 'Right') { 8 } else { 2 }
            $up = if ($btn -eq 'Right') { 16 } else { 4 }
            $count = if ($act -eq 'DoubleClick') { 2 } else { 1 }
            for ($click = 0; $click -lt $count; $click++) {
                if ($wholeScreen) { [NijiComputer]::CheckStop() } else { [NijiComputer]::Guard($target) }
                try {
                    [NijiComputer]::MouseEvent($down, 0)
                    if ($act -eq 'Drag') {
                        for ($step = 1; $step -le 15; $step++) {
                            if ($wholeScreen) { [NijiComputer]::CheckStop() } else { [NijiComputer]::Guard($target) }
                            $dx = [int]($point[0] + ($end[0] - $point[0]) * $step / 15)
                            $dy = [int]($point[1] + ($end[1] - $point[1]) * $step / 15)
                            if (-not [NijiComputer]::SetCursorPos($dx, $dy)) { throw 'Cannot drag cursor' }
                            Start-Sleep -Milliseconds 20
                        }
                    }
                } finally { [NijiComputer]::MouseEvent($up, 0) }
                if ($count -eq 2 -and $click -eq 0) { Start-Sleep -Milliseconds 60 }
            }
        } elseif ($act -eq 'Scroll') {
            [NijiComputer]::MouseEvent(0x800, $amt * 120)
        }
        return
    }

    $mutex = New-Object Threading.Mutex($false, 'LocalNijiKoriComputerUse')
    $locked = $false
    try {
        try { $locked = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw 'Another computer-use step is running' }

        $inputActions = @('Click','DoubleClick','Move','Drag','Scroll','Type','Key')
        $snapshotTokens = @()
        $stepsDone = 0
        $target = [IntPtr]::Zero
        $state = $null
        $resolvedWindow = $null

        # "screen" / "desktop" / "桌面" / "全屏" target the whole virtual
        # desktop: no window to focus, no occlusion guard, so taskbar and
        # desktop icons are reachable like any other point on the display.
        $wholeScreenRequested = $false
        if ($Window) {
            $wkey = $Window.Trim().ToLower()
            if ($wkey -in @('screen', 'desktop', 'display', 'all', '全屏', '屏幕', '桌面', '整个屏幕')) {
                $wholeScreenRequested = $true
                $Window = ''
            }
        }
        if ($WindowId -eq 0 -and $Window) {
            $resolvedWindow = Find-TargetWindow $Window
            if (-not $resolvedWindow) {
                throw ('未找到匹配窗口: ' + $Window + '；先看 action=windows 的标题/进程名，或直接用进程名关键词（如 POWERPNT）。window not found')
            }
            $WindowId = [long]$resolvedWindow.id
        }
        $textValue = Normalize-Text $Text
        if ($TextFile) {
            if ($Text) { throw 'Use either Text or TextFile' }
            $textValue = Normalize-Text ([IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8))
        }

        if ($Action -in @('Observe','Focus')) {
            if ($wholeScreenRequested) {
                $target = [IntPtr]::Zero
            } else {
                if ($WindowId -eq 0) { throw 'WindowId is required; select it from Windows output' }
                $target = [IntPtr]$WindowId
                if (-not [NijiComputer]::IsWindowVisible($target)) { throw 'Target window is unavailable' }
                # Snapshotting needs the target to be foreground; auto-focus so a
                # plain window keyword is enough for both Observe and Focus.
                Set-TargetForeground $target
            }
        } elseif ($Action -in $inputActions) {
            if ($Observation) {
                $state = Get-ObservationState $Observation
                $target = [IntPtr][long]$state.window_id
                if ($WindowId -ne 0 -and [IntPtr]$WindowId -ne $target) { throw 'observation 与 window 不是同一个窗口' }
                if ($target -ne [IntPtr]::Zero) {
                    Set-TargetForeground $target
                    if ([NijiComputer]::ProcessId($target) -ne $state.process_id) { throw 'Window process changed; observe again' }
                    if (([NijiComputer]::Bounds($target) | ConvertTo-Json -Compress) -ne ($state.bounds | ConvertTo-Json -Compress)) {
                        throw 'Window moved or resized; observe again'
                    }
                }
                Invoke-InputStep $target $state $Action $X $Y $ToX $ToY $Button $Amount $textValue $Keys $Mode
                $script:ActionPerformed = $true
            } elseif ($WindowId -ne 0) {
                $target = [IntPtr]$WindowId
                if (-not [NijiComputer]::IsWindowVisible($target)) { throw 'Target window is unavailable' }
                Set-TargetForeground $target
                if ($Action -in @('Type','Key') -and $X -lt 0 -and $Y -lt 0) {
                    # Keyboard-only: focus the window and type; no snapshot base needed.
                    Invoke-InputStep $target $null $Action -1 -1 -1 -1 $Button $Amount $textValue $Keys $Mode
                } else {
                    $state = New-Snapshot $target
                    $snapshotTokens += $state.observation
                    Invoke-InputStep $target $state $Action $X $Y $ToX $ToY $Button $Amount $textValue $Keys $Mode
                }
                $script:ActionPerformed = $true
            } elseif ($wholeScreenRequested) {
                # First step without a snapshot: observe the whole desktop, then act.
                $target = [IntPtr]::Zero
                $state = New-Snapshot $target
                $snapshotTokens += $state.observation
                Invoke-InputStep $target $state $Action $X $Y $ToX $ToY $Button $Amount $textValue $Keys $Mode
                $script:ActionPerformed = $true
            } elseif ($Action -in @('Type','Key')) {
                # Keyboard-only with no window given: use whatever has focus. It
                # must not be the pet itself, or the text lands in its own box.
                $fgId = [long][NijiComputer]::Foreground()
                if ($script:PetPid -gt 0 -and $fgId -ne 0 -and
                    [NijiComputer]::ProcessId([IntPtr]$fgId) -eq $script:PetPid) {
                    throw '当前前台窗口是桌宠自己：请用 window 关键词指定目标窗口再输入'
                }
                $target = [IntPtr]::Zero
                Invoke-InputStep $target $null $Action -1 -1 -1 -1 $Button $Amount $textValue $Keys $Mode
                $script:ActionPerformed = $true
                if ($fgId -ne 0 -and [NijiComputer]::IsWindowVisible([IntPtr]$fgId)) {
                    $fgWin = @([NijiComputer]::Windows()) | Where-Object { $_.id -eq $fgId } | Select-Object -First 1
                    if ($fgWin) { $resolvedWindow = $fgWin; $target = [IntPtr]$fgId }
                }
            } else {
                throw '这个动作需要 observation token 或 window 关键词：先 observe/focus 拿快照（或指定 window）再操作。A valid observation token is required'
            }
        } elseif ($Action -eq 'Steps') {
            $stepList = @(Get-NormalizedSteps)
            if ($stepList.Count -eq 0) { throw 'steps 不能为空' }
            if ($Observation) {
                $state = Get-ObservationState $Observation
                $target = [IntPtr][long]$state.window_id
                if ($WindowId -ne 0 -and [IntPtr]$WindowId -ne $target) { throw 'observation 与 window 不是同一个窗口' }
                if ($target -ne [IntPtr]::Zero) {
                    Set-TargetForeground $target
                    if ([NijiComputer]::ProcessId($target) -ne $state.process_id) { throw 'Window process changed; observe again（窗口进程变了，请重新 observe）' }
                    if (([NijiComputer]::Bounds($target) | ConvertTo-Json -Compress) -ne ($state.bounds | ConvertTo-Json -Compress)) {
                        throw 'Window moved or resized; observe again（窗口已移动或缩放，请重新 observe 再执行步骤）'
                    }
                }
            } elseif ($WindowId -ne 0) {
                $target = [IntPtr]$WindowId
                if (-not [NijiComputer]::IsWindowVisible($target)) { throw 'Target window is unavailable' }
                Set-TargetForeground $target
                $state = New-Snapshot $target
                $snapshotTokens += $state.observation
            } elseif ($wholeScreenRequested) {
                $target = [IntPtr]::Zero
                $state = New-Snapshot $target
                $snapshotTokens += $state.observation
            } elseif (@($stepList | Where-Object { ([string]$_.action) -in @('type','key') }).Count -eq $stepList.Count) {
                # A purely keyboard step list needs no snapshot base: it types into
                # the focused window (never into the pet's own window).
                $fgId = [long][NijiComputer]::Foreground()
                if ($script:PetPid -gt 0 -and $fgId -ne 0 -and
                    [NijiComputer]::ProcessId([IntPtr]$fgId) -eq $script:PetPid) {
                    throw '当前前台窗口是桌宠自己：请用 window 关键词指定目标窗口再执行步骤'
                }
                $fgWin = if ($fgId -ne 0) { @([NijiComputer]::Windows()) | Where-Object { $_.id -eq $fgId } | Select-Object -First 1 } else { $null }
                if ($fgWin) { $resolvedWindow = $fgWin; $target = [IntPtr]$fgId } else { $target = [IntPtr]::Zero }
            } else {
                throw '这个动作需要 observation token 或 window 关键词：先 observe/focus 拿快照（或指定 window）再操作；纯 type/key 的步骤可以不带目标。A valid observation token is required'
            }
            foreach ($step in $stepList) {
                [NijiComputer]::CheckStop()
                $act = ([string]$step.action).ToLower()
                if ([string]::IsNullOrEmpty($act)) { throw 'step.action is required' }
                if ($act -eq 'sleep') {
                    $ms = if ($null -ne $step.ms) { [int]$step.ms } elseif ($null -ne $step.delay_ms) { [int]$step.delay_ms } else { 300 }
                    Start-Sleep -Milliseconds ([Math]::Max(0, [Math]::Min($ms, 10000)))
                    continue
                }
                if ($act -notin $inputActions) { throw ('Unsupported step action: ' + $act + '（可用：click / doubleclick / move / drag / scroll / type / key / sleep）') }
                $sx = if ($null -ne $step.x) { [int]$step.x } else { -1 }
                $sy = if ($null -ne $step.y) { [int]$step.y } else { -1 }
                $stx = if ($null -ne $step.to_x) { [int]$step.to_x } else { -1 }
                $sty = if ($null -ne $step.to_y) { [int]$step.to_y } else { -1 }
                $samt = if ($null -ne $step.amount) { [int]$step.amount } else { 0 }
                $sbtn = if ($step.button) { [string]$step.button } else { 'Left' }
                $smode = if ($step.mode) { [string]$step.mode } else { $Mode }
                Invoke-InputStep $target $state $act $sx $sy $stx $sty $sbtn $samt (Normalize-Text ([string]$step.text)) ([string]$step.keys) $smode
                $script:ActionPerformed = $true
                $stepsDone++
                if (-not $NoSnapshot) {
                    $delay = if ($null -ne $step.delay_ms) { [int]$step.delay_ms } else { $SnapshotDelayMs }
                    if ($delay -gt 0) { Start-Sleep -Milliseconds ([Math]::Min($delay, 15000)) }
                    $snap = New-Snapshot $target
                    $snapshotTokens += $snap.observation
                }
            }
        } else {
            throw ('Unsupported action: ' + $Action)
        }

        if (($Action -in @('Observe','Focus')) -or ($Action -in $inputActions)) {
            if (-not $NoSnapshot) {
                if ($SnapshotDelayMs -gt 0) { Start-Sleep -Milliseconds ([Math]::Min($SnapshotDelayMs, 15000)) }
                $snap = New-Snapshot $target
                $snapshotTokens += $snap.observation
            }
        } elseif ($Action -eq 'Steps') {
            # No step ran (e.g. only "sleep" steps): still return a fresh look.
            if (-not $NoSnapshot -and $snapshotTokens.Count -eq 0) {
                $snap = New-Snapshot $target
                $snapshotTokens += $snap.observation
            }
        }

        $last = ''
        if ($snapshotTokens.Count -gt 0) { $last = [string]$snapshotTokens[-1] }
        $savedPath = ''
        if ($SaveSnapshot -and $last) {
            $srcPng = Join-Path $script:CacheDir ($last + '.png')
            $destDir = Split-Path -Parent $SaveSnapshot
            if ($destDir -and -not [IO.Directory]::Exists($destDir)) { [void][IO.Directory]::CreateDirectory($destDir) }
            Copy-Item -LiteralPath $srcPng -Destination $SaveSnapshot -Force
            $savedPath = $SaveSnapshot
        }
        $lastMeta = $null
        if ($last) {
            try { $lastMeta = Get-Content -LiteralPath (Join-Path $script:CacheDir ($last + '.json')) -Raw | ConvertFrom-Json } catch { }
        }
        $imageWidth = 0; $imageHeight = 0; $method = ''
        if ($lastMeta) {
            $imageWidth = [int]$lastMeta.image_width
            $imageHeight = [int]$lastMeta.image_height
            $method = [string]$lastMeta.method
        }
        $targetId = 0
        $windowInfo = $null
        if ($target -eq [IntPtr]::Zero) {
            $windowInfo = @{ id = 0; title = '整个屏幕（所有显示器）'; process = ''; whole_screen = $true }
        } elseif ($target -ne [IntPtr]::Zero) {
            $targetId = $target.ToInt64()
            $windowInfo = @{ id = $targetId; bounds = [NijiComputer]::Bounds($target) }
            if ($resolvedWindow) {
                $windowInfo['title'] = [string]$resolvedWindow.title
                $windowInfo['process'] = [string]$resolvedWindow.process
            }
        } elseif ($resolvedWindow) {
            $windowInfo = @{ id = [long]$resolvedWindow.id; title = [string]$resolvedWindow.title; process = [string]$resolvedWindow.process }
        }
        $out = [ordered]@{
            status = 'success'
            action = [string]$Action
            action_performed = [bool]$script:ActionPerformed
            observation = $last
            observations = @($snapshotTokens)
            image_width = $imageWidth
            image_height = $imageHeight
            method = $method
            window_id = $targetId
            steps_done = $stepsDone
            saved_path = $savedPath
            window = $windowInfo
        }
        $out | ConvertTo-Json -Depth 6 -Compress
    } finally {
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
} catch {
    $message = [string]$_.Exception.Message
    $errorType = ''
    if ($message -like 'PET_BLOCKS:*') {
        $errorType = 'pet_blocks'
        $message = '操作位置被桌宠自己的窗口挡住：' + $message.Substring(11)
    }
    $payload = [ordered]@{status='error'; action_performed=[bool]$script:ActionPerformed; message=$message}
    if ($errorType) { $payload['error_type'] = $errorType }
    $payload | ConvertTo-Json -Compress
    exit 1
}
