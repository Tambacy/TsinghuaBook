# Full regression run. ASCII only -- Windows PowerShell 5.1 reads .ps1 as GBK
# and mangles UTF-8 Chinese, which produced bogus parse errors.
#
# Run from anywhere:   pwsh -File tools\regress.ps1
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONIOENCODING = 'utf-8'
$env:TSINGHUA_CRAWLER_NO_WEBENGINE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'

$py = Join-Path $root 'venv\Scripts\python.exe'
$fail = @()
$pass = @()

function Run-One($label, $argv) {
    $out = & $script:py @argv 2>&1
    $code = $LASTEXITCODE
    $tail = ($out | Select-Object -Last 1)
    if ($code -eq 0) {
        Write-Output ("  OK   {0,-24} {1}" -f $label, $tail)
        $script:pass += $label
    } else {
        Write-Output ("  FAIL {0,-24} exit={1}  {2}" -f $label, $code, $tail)
        Write-Output "       ---- last 25 lines ----"
        $out | Select-Object -Last 25 | ForEach-Object { "       $_" }
        $script:fail += $label
    }
}

Write-Output "=== compile ==="
& $py -m compileall -q crawler gui.py cli.py launcher.py 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Output "  OK   compileall"; $pass += 'compileall' }
else { Write-Output "  FAIL compileall"; $fail += 'compileall' }

Write-Output ""
Write-Output "=== unit / integration ==="
Run-One 'test_engine'          @('tests\test_engine.py')
Run-One 'test_worker'          @('tests\test_worker.py')
Run-One 'test_store_queue'     @('tests\test_store_queue.py')
Run-One 'test_tokeninfo'       @('tests\test_tokeninfo.py')
Run-One 'test_relocate'        @('tests\test_relocate.py')
Run-One 'test_updater'         @('tests\test_updater.py')
Run-One 'test_gui_integration' @('tests\test_gui_integration.py')
Run-One 'test_queue_threading' @('tests\test_queue_threading.py')

Write-Output ""
Write-Output "=== gui smoke ==="
Run-One 'smoke_window'         @('tests\smoke_window.py')
Run-One 'smoke_update'         @('tests\smoke_update.py')
Run-One 'smoke_login'          @('tests\smoke_login.py')
Run-One 'smoke_layers'         @('tests\smoke_layers.py')
Run-One 'smoke_frame'          @('tests\smoke_frame.py')

Write-Output ""
Write-Output "=== design / asset checks ==="
Run-One 'check_version'        @('tools\check_version.py')
Run-One 'check_bundle'         @('tools\check_bundle.py')
Run-One 'check_secrets'        @('tools\check_secrets.py')
Run-One 'check_fade_opaque'    @('tools\check_fade_opaque.py')
# check_sky_edges samples real window pixels, so it cannot run offscreen --
# globally setting QT_QPA_PLATFORM=offscreen made it report "window 0x0".
# Clear the variable for this one run only; it is not a regression.
$savedQpa = $env:QT_QPA_PLATFORM
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Run-One 'check_sky_edges'      @('tools\check_sky_edges.py')
$env:QT_QPA_PLATFORM = $savedQpa
Run-One 'check_backdrop'       @('tools\check_backdrop_contrast.py')
Run-One 'check_design'         @('tools\check_design_language.py')
Run-One 'check_webengine'      @('tools\check_webengine.py')

Write-Output ""
Write-Output "=== selftest ==="
Run-One 'selftest'             @('-m', 'crawler.selftest')

Write-Output ""
Write-Output "============================================"
Write-Output ("passed {0}, failed {1}" -f $pass.Count, $fail.Count)
if ($fail.Count -gt 0) {
    Write-Output ("failed: {0}" -f ($fail -join ', '))
    Write-Output "REGRESSION FAIL"
    exit 1
}
Write-Output "REGRESSION PASS"
exit 0
