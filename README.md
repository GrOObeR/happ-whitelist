# Happ WhiteList Auto

Автоматическая подписка для **Happ**.

Что делает репозиторий:

- раз в час скачивает исходный VLESS-список;
- использует зеркала, если основной URL временно недоступен;
- оставляет только строки `vless://`;
- удаляет дубли, сохраняя исходный порядок;
- не перезаписывает `happ.txt`, если источники сломались или вернули подозрительно мало конфигураций;
- добавляет метаданные Happ:
  - `#profile-title: WhiteList Auto`
  - `#profile-update-interval: 1`

## 1. Создание репозитория

Создай **public**-репозиторий GitHub, например:

`happ-whitelist`

Загрузи в корень содержимое этого архива **с сохранением структуры каталогов**:

```text
happ-whitelist/
├── .github/
│   └── workflows/
│       └── update.yml
├── update.py
├── sources.txt
├── happ.txt
└── README.md
```

После загрузки файлов workflow должен запуститься автоматически.

Также его можно запустить вручную:

`Actions -> Update Happ subscription -> Run workflow`

## 2. Если GitHub Actions не может сделать push

Открой:

`Settings -> Actions -> General -> Workflow permissions`

и разреши:

`Read and write permissions`

Затем снова запусти workflow.

## 3. Ссылка для Happ

После первого успешного workflow открой `happ.txt`.

Для репозитория:

`https://github.com/LOGIN/happ-whitelist`

ссылка подписки будет:

`https://raw.githubusercontent.com/LOGIN/happ-whitelist/main/happ.txt`

где `LOGIN` — твой GitHub-логин.

Эту одну ссылку можно добавить в Happ на Windows и телефонах.

## 4. Как добавить ещё один источник

Открой `sources.txt`.

Каждый новый **независимый** источник добавляй с новой строки:

```text
https://example.com/list1.txt
https://example.com/list2.txt
```

Если это зеркала одного и того же списка, указывай их в одной строке через `|`:

```text
https://mirror1.example/list.txt | https://mirror2.example/list.txt
```

В этом случае скрипт скачает только первое доступное зеркало, а не будет бессмысленно добавлять один и тот же список несколько раз.

## 5. Что будет происходить каждый час

```text
sources.txt
    ↓
GitHub Actions
    ↓
update.py
    ↓
фильтр VLESS + удаление дублей
    ↓
happ.txt
    ↓
Happ
```

В самом `happ.txt` передаются:

```text
#profile-title: WhiteList Auto
#profile-update-interval: 1
```

То есть Happ получает рекомендуемый интервал обновления **1 час**.

> Если в самом Happ пользователь вручную установил другой интервал обновления,
> клиентская настройка может иметь приоритет над значением из подписки.

## Примечание

GitHub Actions запускает расписание примерно по cron, но не гарантирует старт
ровно до секунды. Поэтому `17 * * * *` означает "примерно один раз в час на
17-й минуте", возможна небольшая задержка со стороны GitHub.
