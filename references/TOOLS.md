# Отобранные инструменты

Переносим конкретные способы анализа и проверки, не чужой launch/UI-стиль целиком.

- https://github.com/charlie947/motion-graphics-skills — reference-to-motion: разбор темпа/перехода/типографики/света/главного действия. У нас разбор уже дан для V2; фон пользователя и последние замечания имеют приоритет.
- https://github.com/LottieFiles/motion-design-skill — choreography/easing; их UI-таблицы времени не являются таймингом фильма.
- https://github.com/whaleyxbt/claude-motion — review-loop: проверка читаемости, обрезаний, времени удержания, общей шкалы времени.
- https://github.com/Barty-Bart/motion-graphics — object-separation с SAM 2.1 при необходимости видеовырезки. Сначала короткий участок и край/маска, потом весь клип; Python-зависимости в отдельном проектном venv, никаких глобальных скиллов.
- https://github.com/howseen-ai/claude-motion-design — seek(t), проверки вспышек/переходов и субкадровое motion blur. Blur в базовом экспортере 0.2.0 не реализован.
- https://github.com/greensock/gsap-skills — API GSAP, только при использовании GSAP в конкретной сцене.
- https://github.com/heygen-com/hyperframes — возможный альтернативный HTML-рендерер; не установлен по умолчанию.
- https://github.com/remotion-dev/skills — применять только при выбранном Remotion; его runtime и лицензия проверяются отдельно.

Полный обзор 15 репозиториев: GITHUB_MOTION_REVIEW_2026-10-11.md. Сам обзор выполнен до выпуска пакета, его отметка «ничего не установлено» относится к тому этапу. В текущем релизе установлен только наш скилл и собственный базовый runtime; сторонние большие наборы — ссылки, не активные правила.
