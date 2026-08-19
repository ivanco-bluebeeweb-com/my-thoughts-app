# Scenario Tests (PST) — My Thoughts App

Метод: `Docs/session-notes/SCENARIO_TESTING_STANDARD.md`.

---

## Прогон 2026-08-19

**Существующее покрытие до PST:** 27 тестов, приложение уже CLEAN по
предыдущему сквозному пост-аудиту (18 функций, ни одной `destructive` —
разумно: всё либо архивируется обратимо, либо отзывается обратимо, нет
безвозвратного удаления пользовательских данных). Аудит по точному имени
функции нашёл **3 функции, никогда не тестировавшиеся**:

`attach_voice_note`, `rename_thought`, `quick_new_thought_chain`.

**Новый файл:** `tests/test_pst_scenarios.py` — 7 сценариев: для
`attach_voice_note` — happy path с созданием нового Thought "на лету"
(проверено, что сообщение реально приземлилось в реальном Thought, не
просто заявлено в summary), happy path с существующим Thought, error на
несуществующий `thought_id`; для `rename_thought` — happy path
(подтверждено, что новое имя реально сохранилось в сторе через
последующий `get_thought`, а не просто что вызов не упал), error на
несуществующий id; для `quick_new_thought_chain` — happy path с явным
именем и happy path с пустым именем (докстрока обещает "sensible
default the user can rename later").

Одна собственная ошибка в черновике: `get_thought` возвращает
`ThoughtMessageList`, не объект с полем `.title` — заголовок доступен
только через строку `summary`. Тест переписан на проверку `summary`.

### Результат

34/34 тестов зелёные (27 существующих + 7 новых). **Реальных багов в
приложении не найдено.**

---
