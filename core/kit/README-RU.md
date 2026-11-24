# B62 server kit — запуск пользователем

Этот каталог входит в полный immutable source. Он не арендует сервер, не устанавливает WSL и ничего не отправляет. Нужны отдельно разрешённый Linux и место для общего /data. Build/wheel availability локально NOT_RUN. Не переносите Windows .venv. Build только на разрешённой целевой машине:

    docker build -f kit/Dockerfile -t kaze-b62-candidate .

Зафиксируйте полученный image ID и не rebuild между resume. Compose не публикует порты, network_mode:none, source read-only; /data — один общий каталог для ВСЕХ designs на данном диске. Обеспечьте доступ UID10001. Secret/provider credentials не требуются и не помещаются в пакет.

Команды внутри того же image/runtime (укажите фактический bind mount /data):

    python -B kit/serverctl.py doctor
    python -B kit/serverctl.py qualify-protocol --output /data/linux-protocol
    python -B kit/serverctl.py plan --input /data/original-v7.json --output /data/pilot.json --seconds 86400 --policy /data/pilot-policy.json --rate 0.0625 --currency USD --max-cost 20
    python -B kit/serverctl.py run --plan /data/pilot.json
    python -B kit/serverctl.py status --plan /data/pilot.json
    python -B kit/serverctl.py stop --plan /data/pilot.json
    python -B kit/serverctl.py resume --plan /data/pilot.json
    python -B kit/serverctl.py export-result --plan /data/pilot.json --output /data/pilot-result.zip
    python -B kit/serverctl.py inspect-result --input /data/pilot-result.zip

Policy — точный JSON dataclass LifetimeCampaignPolicy; пример без расчёта печатает examples/m8_lifetime_campaign.py (поле policy). Для pilot заранее объявите2–8 primary,1–2 diagnostics и достаточные wall caps; default lifetime reserve значительно больше пилотного диска. Не редактируйте policy/input/source после plan/store. Plan проверяет genuine V7, сохраняет original/duration/accounting этапы и whole source. На Linux создаётся новый initial plan; Windows native не мигрирует. Assumption/rates original input не заменяются автоматически.

Для диагностики после completed target:

    python -B kit/serverctl.py diagnostic --plan /data/pilot.json --parent-job-id <completed-main> --checkpoint-sha256 <retained-RESTORED-sha> --verbose

Диагностическая quota реально подключена. Предшественник должен содержать retained checkpoint с publication/streams; нельзя подставить CSV или один native JSON. Read-only результат можно открыть локальным Workbench portable inspector; продолжение — только полный прежний store, same source/runtime.

15-летний plan: --seconds473364000 и --mode long, без пробела после --seconds в этом описании означает обычные два CLI аргумента. Для long нужен SERVER-PILOT-PASS.json формата B62_GENUINE_TARGET_EVIDENCE_REFERENCES_V1: source_manifest_sha256, runtime, reference_store, continuation_store, protocol_receipts. Это ССЫЛКИ на genuine Linux receipts/day/native science, не booleans. admit_acceptance заново проверяет их; record нельзя выдумать для обхода gate. Непроведённый target pilot остаётся SERVER_ACCEPTANCE_PENDING. Год/15лет на ноутбуке данным заданием не запускаются.

Штатная пауза — serverctl stop в другом процессе того же immutable image, затем status и проверка settlement. Docker stop/SIGTERM не гарантирует checkpoint. Unknown launch не перезапускается автоматически. Нет restart:always.

Default reserve включает всю историю, native+streams, source package и backup/export allowance. Pool считает один физический volume, не сумму mirror devices. Measured bytes выводятся отдельно от reservation; все stores должны использовать один shared /data. Диск может исчерпаться от внешних файлов — admission остановит новые jobs. Нельзя удалять историю ради продолжения.

Тариф/estimate — условная арифметика, не provider spending cap. Диск, IP, idle, backup, налоги и передача отдельно. Stop/completion НЕ прекращает billing. Перед самостоятельным удалением платных ресурсов выгрузите read-only result И полный store/initial/source/runtime backup, проверьте SHA-256 и пробное read-only открытие. Этот helper не удаляет ни сервер, ни store.
