# Pipeline Roadmap

Продовая схема выполнения одного локального запуска сервиса.

## 0. Входы

- Команда: `python src/main.py <event_folder> <form_id>`.
- `event_folder`: папка Яндекс.Диска с исходными event-фото.
- `form_id`: id папки Яндекс.Форм `/Yandex.Forms/<form_id>/`.
- `.env`: содержит `YANDEX_DISK_TOKEN`.
- Модели: YuNet и SFace в `data/models/`.
- Опции: `--similarity-threshold`, `--cleanup-local`, `--debug-logs`.

## 1. `main()`

- Файл: [`src/main.py`](src/main.py).
- Отвечает за: запуск сервиса из CLI, сбор конфигурации и передачу управления
  основному workflow.
- Получает:
  - `event_folder`;
  - `form_id`;
  - CLI-опции.
- Делает:
  - парсит CLI-аргументы через `build_parser()`;
  - настраивает логирование через `configure_logging(...)`;
  - собирает `DistributionConfig`;
  - вызывает `run_distribution(event_folder, form_id, config=...)`;
  - логирует `DistributionResult.safe_summary()`;
  - вызывает `cleanup_local_artifacts(result)`, если включен `--cleanup-local`.
- Ловит:
  - `FormsExportError`, `FaceAnalysisError`, `DiskApiError` -> exit code `1`;
  - `ValueError` -> exit code `2`.

## 2. `run_distribution(...)`

- Файл: [`src/photo_distribution_utils/workflow.py`](src/photo_distribution_utils/workflow.py).
- Отвечает за: полный сценарий обработки одной event-папки: проверить исходную
  папку, импортировать форму, скачать фото для анализа, распознать людей,
  построить remote copy-plan, применить его на Яндекс.Диске и вернуть счетчики.
- Получает:
  - распарсенный `event_folder`;
  - распарсенный `form_id`;
  - явный `DistributionConfig`.
- Делает по порядку:
  - `2.1. YandexDiskClient.from_env()`;
  - `2.2. validate_cloud_event_folder(...)`;
  - `2.3. prepare_event_artifact_paths(...)`;
  - `2.4. ingest_forms_export(...)`;
  - `2.5. download_event_photos(...)`;
  - `2.6. build_distribution_output_folders(...)`;
  - `2.7. FaceAnalyzer(...)`;
  - `2.8. FaceAnalyzer.analyze_distribution(...)`;
  - `2.9. build_distribution_copy_plan(...)`;
  - `2.10. apply_distribution_plan(...)`;
  - `2.11. DistributionResult(...)`.
- Возвращает:
  - `DistributionResult`.

### 2.1. `YandexDiskClient.from_env()`

- Файл: [`src/yandex_disk/client.py`](src/yandex_disk/client.py).
- Отвечает за: создание клиента Яндекс.Диска для всех remote-операций запуска.
- Делает:
  - читает `YANDEX_DISK_TOKEN`;
  - создает авторизованный клиент API Яндекс.Диска.
- Возвращает:
  - `YandexDiskClient`.

### 2.2. `validate_cloud_event_folder(...)`

- Файл: [`src/photo_distribution_utils/cloud_files.py`](src/photo_distribution_utils/cloud_files.py).
- Отвечает за: проверку, что `event_folder` является корректной и доступной
  папкой Яндекс.Диска.
- Проверяет формат:
  - path не пустой;
  - path начинается с `/`;
  - path не равен `/`;
  - нет пробелов вокруг path;
  - нет trailing `/`;
  - нет пустых сегментов вида `//`.
- Вызывает:
  - `disk_client.get_resource(event_folder)`;
  - retry выполняет `@retry_yandex_disk_operation` на методе клиента.
- Проверяет metadata:
  - resource существует;
  - resource доступен текущему токену;
  - metadata содержит `type == "dir"`.
- Возвращает:
  - `None` при успехе.

### 2.3. `prepare_event_artifact_paths(...)`

- Файл: [`src/photo_distribution_utils/event_artifacts.py`](src/photo_distribution_utils/event_artifacts.py).
- Отвечает за: локальные пути артефактов для уже проверенной event-папки.
- Получает:
  - canonical Yandex Disk event folder path;
  - `DistributionConfig`.
- Делает:
  - вызывает `local_event_key_from_folder(event_folder)`;
  - создает `data/event_photos/<local_event_key>/`;
  - собирает `EventArtifactPaths`.
- Возвращает:
  - `EventArtifactPaths` с полями:
    - `event_folder`;
    - `local_event_key`;
    - `local_event_photos_dir`;
    - `copy_plan_dir`;
    - `copy_plan_path`.

#### 2.3.1. `local_event_key_from_folder(...)`

- Файл: [`src/photo_distribution_utils/event_artifacts.py`](src/photo_distribution_utils/event_artifacts.py).
- Отвечает за: filesystem-safe ключ события для локальных артефактов.
- Пример:
  - remote path: `/events/test event 001`;
  - local key: `events_test_event_001`.
- Используется для:
  - `data/event_photos/<local_event_key>/`;
  - `data/distribution_plans/<local_event_key>/`.

### 2.4. `ingest_forms_export(...)`

- Файл: [`src/forms_export/ingest.py`](src/forms_export/ingest.py).
- Отвечает за: импорт участников и reference-фото из папки выгрузки
  Яндекс.Форм.
- Делает:
  - вызывает `find_latest_json_export(...)`;
  - скачивает самую свежую JSON-выгрузку;
  - вызывает `load_participants(...)`;
  - скачивает reference images участников;
  - собирает `FormsIngestResult`.
- Пишет:
  - `data/forms/exports/<export>.json`;
  - `data/forms/references/...`.
- Возвращает:
  - `FormsIngestResult`.

#### 2.4.1. `find_latest_json_export(...)`

- Файл: [`src/forms_export/ingest.py`](src/forms_export/ingest.py).
- Отвечает за: выбор самой свежей `.json` выгрузки в
  `/Yandex.Forms/<form_id>/`.
- Проверяет:
  - в папке есть хотя бы один `.json`;
  - у выбранного resource есть Yandex Disk `path`.
- Возвращает:
  - remote path выбранной JSON-выгрузки.

#### 2.4.2. `load_participants(...)`

- Файл: [`src/forms_export/participants.py`](src/forms_export/participants.py).
- Отвечает за: парсинг скачанного JSON Яндекс.Форм в записи участников.
- Делает:
  - читает поля по позиции через `FORM_FIELD_ORDER`;
  - игнорирует текст вопросов;
  - проверяет обязательные значения;
  - проверяет от одного до трех reference image paths;
  - отклоняет дубли email.
- Возвращает:
  - `list[Participant]`.

### 2.5. `download_event_photos(...)`

- Файл: [`src/photo_distribution_utils/cloud_files.py`](src/photo_distribution_utils/cloud_files.py).
- Отвечает за: локальную загрузку исходных event-фото для face analysis.
- Делает:
  - читает top-level resources внутри `event_folder`;
  - оставляет image files по расширению;
  - скачивает их в `data/event_photos/<local_event_key>/`;
  - логирует прогресс скачивания каждые 10 файлов и финальный счетчик;
  - перезаписывает одноименные локальные файлы прошлого запуска.
- Возвращает:
  - `list[EventPhotoRecord]`.

### 2.6. `build_distribution_output_folders(...)`

- Файл: [`src/photo_distribution_utils/output_files_structure.py`](src/photo_distribution_utils/output_files_structure.py).
- Отвечает за: имена выходных папок участников и карантина на Яндекс.Диске.
- Делает:
  - превращает display names участников в Disk-safe folder names;
  - разрешает дубли имен через суффиксы;
  - сохраняет configured quarantine folder name.
- Возвращает:
  - `DistributionOutputFolders`.

### 2.7. `FaceAnalyzer(...)`

- Файл: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py).
- Отвечает за: создание YuNet/SFace analyzer object для текущего запуска.
- Получает:
  - YuNet model path;
  - SFace model path;
  - `YuNetConfig`.
- Возвращает:
  - `FaceAnalyzer`.

### 2.8. `FaceAnalyzer.analyze_distribution(...)`

- Файл: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py).
- Отвечает за: весь face-analysis текущего события: reference embeddings,
  event face embeddings и reference/event matching.
- Получает:
  - imported reference images;
  - downloaded event photo records;
  - similarity threshold.
- Делает:
  - вызывает `_compute_reference_embeddings(...)`;
  - вызывает `_analyze_event_photos(...)`;
  - использует `embed(...)` для reference и event photos;
  - использует `match_embedding(...)` для event/reference comparison.
- Возвращает:
  - `FaceAnalysisStepResult`.

#### 2.8.1. `detect(image)`

- Файл: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py).
- Отвечает за: детекцию лиц на одной картинке через YuNet.
- Возвращает:
  - `list[FaceDetection]`.

#### 2.8.2. `embed(image, detections=None)`

- Файл: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py).
- Отвечает за: получение SFace embeddings с одной картинки.
- Делает:
  - детектирует лица, если detections не переданы;
  - выравнивает найденные лица через SFace;
  - считает embedding vectors.
- Возвращает:
  - `list[FaceEmbedding]`.

#### 2.8.3. `match_embedding(query_vector, references, min_score=None)`

- Файл: [`src/face_analysis/analyzer.py`](src/face_analysis/analyzer.py).
- Отвечает за: сравнение одного event face embedding с reference embeddings.
- Возвращает:
  - отсортированные reference scores выше `min_score`.

### 2.9. `build_distribution_copy_plan(...)`

- Файл: [`src/photo_distribution_utils/output_files_structure.py`](src/photo_distribution_utils/output_files_structure.py).
- Отвечает за: преобразование face matches в remote-copy операции
  Яндекс.Диска и сохранение этого решения в `copy_plan.json`.
- Получает:
  - downloaded event photo records;
  - accepted face matches;
  - participant/quarantine output folder names;
  - event folder path;
  - copy plan JSON path.
- Делает:
  - направляет matched photos во все matched participant folders;
  - направляет unmatched photos в quarantine;
  - создает remote source/destination copy records;
  - пишет `data/distribution_plans/<local_event_key>/copy_plan.json`.
- JSON содержит:
  - version;
  - planned/quarantined counters;
  - remote source/destination paths для каждой planned copy.
- Возвращает:
  - `CopyPlanBuildResult`.

### 2.10. `apply_distribution_plan(...)`

- Файл: [`src/photo_distribution_utils/apply_distribution_plan.py`](src/photo_distribution_utils/apply_distribution_plan.py).
- Отвечает за: применение distribution plan на Яндекс.Диске через remote-to-remote
  copy.
- Делает:
  - вызывает `disk_client.ensure_folder(...)` для каждой participant folder;
  - вызывает `disk_client.ensure_folder(...)` для quarantine folder;
  - вызывает `disk_client.copy_resource(..., overwrite=True)` для каждой
    строки плана.
- Пишет:
  - Yandex Disk: `<event_folder>/<participant_folder>/<photo>`;
  - Yandex Disk: `<event_folder>/quarantine/<photo>`.
- Возвращает:
  - `DistributionPlanApplyResult`.

### 2.11. `DistributionResult(...)`

- Файл: [`src/photo_distribution_utils/apply_distribution_plan.py`](src/photo_distribution_utils/apply_distribution_plan.py).
- Отвечает за: публичные счетчики и локальные artifact paths завершенного
  запуска.
- Содержит:
  - `DistributionCounters`;
  - `DistributionArtifacts`.
- Используется для:
  - логирования CLI summary;
  - опциональной очистки локальных артефактов.

## 3. `cleanup_local_artifacts(...)`

- Файл: [`src/photo_distribution_utils/apply_distribution_plan.py`](src/photo_distribution_utils/apply_distribution_plan.py).
- Вызывается из:
  - `main()` после успешного `run_distribution(...)`, если включен
    `--cleanup-local`.
- Отвечает за: удаление private local artifacts, созданных основным workflow.
- Удаляет:
  - `data/forms/`;
  - папку текущего события внутри `data/event_photos/`;
  - папку текущего события внутри `data/distribution_plans/`.
- Проверяет:
  - каждый удаляемый path находится внутри project `data/`.

## 4. Логирование

- Файл: [`src/app_logging.py`](src/app_logging.py).
- Отвечает за: production-facing console/file logs.
- Пишет:
  - логи в консоль;
  - `data/logs/photo_distributor.log`.
- Использует:
  - `safe_exception_message(...)`;
  - `utils.redact_personal_data(...)` для последней линии редактирования логов;
  - source metadata в формате `package:module:function`, например
    `photo_distribution_utils:cloud_files:download_event_photos`;
  - `DiskApiError.safe_message()`;
  - `FormsExportError.safe_message()`;
  - `FaceAnalysisError.safe_message()`;
  - `DistributionResult.safe_summary()`.
