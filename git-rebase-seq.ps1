param([string]$path)
$content = Get-Content -Raw $path
$content = $content -replace '^pick 4becd68b971f30c8fd0dc4cc176f9c59188c4092','reword 4becd68b971f30c8fd0dc4cc176f9c59188c4092'
$content = $content -replace '^pick 12bc261e0fb61c25282b17d1d44b0ac0eaba9e55','reword 12bc261e0fb61c25282b17d1d44b0ac0eaba9e55'
$content = $content -replace '^pick b1f408464b539db473a314f40e20609dbdb010f7','reword b1f408464b539db473a314f40e20609dbdb010f7'
Set-Content -Path $path -Value $content -NoNewline