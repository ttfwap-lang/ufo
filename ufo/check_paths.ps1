$paths = @("webapp","miniapp","tgapp","telegram-app","bot","horoscope","daily","forecast","api/horoscope","api/daily","v1/horoscope","astro","zodiac","signs")
foreach ($p in $paths) {
    $code = C:\Windows\System32\curl.exe -s -o NUL -w "%{http_code}" "https://astrologyscience.online/$p" 2>&1
    if ($code -ne "404") { Write-Host "$p -> $code" }
}