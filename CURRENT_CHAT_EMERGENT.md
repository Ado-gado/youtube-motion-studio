# Исправление для открытого чата Emergent

```text
Обнови youtube-motion-studio из main до 0.3.3 или новее, сохрани местные сцены и правила, затем повтори локальную установку и прочитай LOCAL_FONTS.md, LOCAL_RENDER.md и свежие AGENTS/STYLE/WORKFLOW/скилл:
https://github.com/Ado-gado/youtube-motion-studio

Lumios Brush Regular будет подключаться на моём ПК. Не проси загрузить Adobe-файл в Emergent, не заменяй шрифт и не останавливай из-за него установку или сборку сцены. Во время установки только doctor/audit, без Гагарина и других тестовых роликов.

Для моего текущего задания подготовь scene.html, local-fonts.json рядом с ним и редактируемый text.json/config. Перед измерением текста сцена ждёт MOTION_LOCAL_FONTS_READY и пересчитывает раскладку по TEXT_LAYOUT.md, затем выставляет MOTION_TEXT_LAYOUT_READY=true. В облаке сохраняй font_status=pending_local_verification; проверяй доступные материалы/движение/переходы, не объявляй финальную типографику проверенной.

Упакуй только текущую сцену со всеми материалами, ASSETS.md и CREDITS.md через pack_scene.py и дай проверенную ссылку на motion-job-*.zip. Файл Adobe Fonts в архив не включать. MP4 создаст моя очередь на ПК. Не делай сайт и не запускай полный облачный рендер. Без текущего задания сообщи готовность и жди.
```
