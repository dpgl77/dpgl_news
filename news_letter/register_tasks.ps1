$ErrorActionPreference = "Stop"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$daily = New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c cd /d "C:\to_sync\prog\GITHUB\dpgl_news" && grok --yolo --prompt-file "news_letter\publish_prompt.txt"'
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At 9:30AM
Register-ScheduledTask -TaskName "DPGL_News_Newsletter_Sync" -Action $daily -Trigger $dailyTrigger -Settings $settings -Description "Сверка news_letter/index.html и публикация ссылок на новые PDF в @dpgl_news" -Force | Out-Null

$python = (Get-Command python).Source
$gate = New-ScheduledTaskAction -Execute $python -Argument '"C:\to_sync\prog\GITHUB\dpgl_news\news_letter\telegram_gate.py"' -WorkingDirectory "C:\to_sync\prog\GITHUB\dpgl_news\news_letter"
$gateTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 9999)
Register-ScheduledTask -TaskName "DPGL_News_Newsletter_Gate" -Action $gate -Trigger $gateTrigger -Settings $settings -Description "Выдача PDF бюллетеней только подписчикам @dpgl_news" -Force | Out-Null

Get-ScheduledTask -TaskName "DPGL_News_Newsletter_Sync","DPGL_News_Newsletter_Gate" | Format-Table TaskName, State
