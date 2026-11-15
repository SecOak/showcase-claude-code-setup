try {
    $stdin = [Console]::In.ReadToEnd()
    $j = $stdin | ConvertFrom-Json
    $cmd = $j.tool_input.command
    if (-not $cmd) { $cmd = ($j.tool_input | ConvertTo-Json -Compress -Depth 5) }
    $mode = $j.permission_mode
    if (-not $mode) { $mode = 'ABSENT' }
    $line = "{0} | {1} | {2} | {3} | {4}" -f (Get-Date -Format o), $j.session_id, $mode, $j.tool_name, $cmd
    Add-Content -LiteralPath (Join-Path $env:USERPROFILE '.claude\permission-prompts.log') -Value $line
} catch {}
