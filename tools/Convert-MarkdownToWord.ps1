<#
    Convert-MarkdownToWord.ps1
    Markdown -> .docx via an intermediate HTML file opened in Word (no pandoc on this host).
    Handles the subset used in our handouts: h1-h3, paragraphs, bold/italic/code,
    bullet + numbered lists, pipe tables, horizontal rules.
#>
param(
    [Parameter(Mandatory)][string]$InputPath,
    [Parameter(Mandatory)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function ConvertTo-Inline([string]$t) {
    # order matters: escape HTML first, then apply markup
    $t = $t -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;'
    $t = [regex]::Replace($t, '`([^`]+)`', '<code>$1</code>')
    $t = [regex]::Replace($t, '\*\*([^*]+)\*\*', '<strong>$1</strong>')
    $t = [regex]::Replace($t, '(?<![\*\w])\*([^*]+)\*(?!\*)', '<em>$1</em>')
    return $t
}

$lines = [System.IO.File]::ReadAllLines($InputPath)
$sb    = [System.Text.StringBuilder]::new()
$i     = 0
$list  = $null   # 'ul' | 'ol' | $null

function Close-List {
    if ($script:list) { [void]$script:sb.AppendLine("</$script:list>"); $script:list = $null }
}

while ($i -lt $lines.Count) {
    $line = $lines[$i]

    # --- pipe table: a header row followed by a |---|---| separator ---
    if ($line -match '^\s*\|' -and ($i + 1) -lt $lines.Count -and $lines[$i + 1] -match '^\s*\|[\s\-:|]+\|\s*$') {
        Close-List
        [void]$sb.AppendLine('<table border="1" cellspacing="0" cellpadding="5">')
        $cells = ($line.Trim().Trim('|') -split '\|') | ForEach-Object { ConvertTo-Inline $_.Trim() }
        [void]$sb.AppendLine('<tr>' + (($cells | ForEach-Object { "<th>$_</th>" }) -join '') + '</tr>')
        $i += 2
        while ($i -lt $lines.Count -and $lines[$i] -match '^\s*\|') {
            $cells = ($lines[$i].Trim().Trim('|') -split '\|') | ForEach-Object { ConvertTo-Inline $_.Trim() }
            [void]$sb.AppendLine('<tr>' + (($cells | ForEach-Object { "<td>$_</td>" }) -join '') + '</tr>')
            $i++
        }
        [void]$sb.AppendLine('</table>')
        continue
    }

    switch -Regex ($line) {
        '^\s*$'            { Close-List; break }
        '^---+\s*$'        { Close-List; [void]$sb.AppendLine('<hr/>'); break }
        '^###\s+(.*)'      { Close-List; [void]$sb.AppendLine('<h3>' + (ConvertTo-Inline $Matches[1]) + '</h3>'); break }
        '^##\s+(.*)'       { Close-List; [void]$sb.AppendLine('<h2>' + (ConvertTo-Inline $Matches[1]) + '</h2>'); break }
        '^#\s+(.*)'        { Close-List; [void]$sb.AppendLine('<h1>' + (ConvertTo-Inline $Matches[1]) + '</h1>'); break }
        '^\s*[-*]\s+(.*)'  {
            if ($list -ne 'ul') { Close-List; [void]$sb.AppendLine('<ul>'); $list = 'ul' }
            [void]$sb.AppendLine('<li>' + (ConvertTo-Inline $Matches[1]) + '</li>'); break
        }
        '^\s*\d+\.\s+(.*)' {
            if ($list -ne 'ol') { Close-List; [void]$sb.AppendLine('<ol>'); $list = 'ol' }
            [void]$sb.AppendLine('<li>' + (ConvertTo-Inline $Matches[1]) + '</li>'); break
        }
        default {
            # join wrapped lines into one paragraph
            $para = @($line)
            while (($i + 1) -lt $lines.Count -and $lines[$i + 1].Trim() -ne '' -and
                   $lines[$i + 1] -notmatch '^\s*([-*]\s|\d+\.\s|#|\||---+\s*$)') {
                $i++; $para += $lines[$i]
            }
            Close-List
            [void]$sb.AppendLine('<p>' + (ConvertTo-Inline ($para -join ' ')) + '</p>')
        }
    }
    $i++
}
Close-List

$html = @"
<html><head><meta charset="utf-8"/>
<style>
 body   { font-family: Calibri, sans-serif; font-size: 11pt; }
 h1     { font-size: 20pt; }
 h2     { font-size: 15pt; }
 h3     { font-size: 12pt; }
 table  { border-collapse: collapse; }
 th     { background: #eeeeee; text-align: left; }
 code   { font-family: Consolas, monospace; }
</style></head><body>
$($sb.ToString())
</body></html>
"@

$tmpHtml = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), '.html')
[System.IO.File]::WriteAllText($tmpHtml, $html, (New-Object System.Text.UTF8Encoding $true))

$word = $null; $doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $doc = $word.Documents.Open($tmpHtml, [ref]$false, [ref]$false)
    $doc.SaveAs([ref]$OutputPath, [ref]16)   # 16 = wdFormatDocumentDefault (.docx)
    $pages = $doc.ComputeStatistics(2)       # 2 = wdStatisticPages
    $words = $doc.ComputeStatistics(0)       # 0 = wdStatisticWords
    $doc.Close([ref]$false); $doc = $null
    "OK: $OutputPath  ($pages pages, $words words)"
}
finally {
    if ($doc)  { $doc.Close([ref]$false)  | Out-Null }
    if ($word) { $word.Quit() | Out-Null; [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
    Remove-Item $tmpHtml -ErrorAction SilentlyContinue
}
