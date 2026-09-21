(function () {
    function boot() {
        const root = document.querySelector('[data-irz-root]');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';

        const devicesNode = root.querySelector('[data-irz-devices]');
        const logsNode = root.querySelector('[data-irz-logs]');
        const gatewayNode = root.querySelector('[data-irz-gateway]');
        const selectedNode = root.querySelector('[data-irz-selected]');
        const messageNode = root.querySelector('[data-irz-message]');
        const form = root.querySelector('[data-irz-send-form]');
        const input = root.querySelector('[data-irz-hex]');
        const sendButton = root.querySelector('[data-irz-send]');
        const listenButton = root.querySelector('[data-irz-listen]');
        const exportLink = root.querySelector('[data-irz-export]');
        const labDevice = root.querySelector('[data-irz-lab-device]');
        const preset = root.querySelector('[data-irz-preset]');
        const labHex = root.querySelector('[data-irz-lab-hex]');
        const crc = root.querySelector('[data-irz-crc]');
        const append = root.querySelector('[data-irz-append]');
        const testForm = root.querySelector('[data-irz-test-form]');
        const testButton = root.querySelector('[data-irz-test-send]');
        const testMessage = root.querySelector('[data-irz-test-message]');
        const experimentsNode = root.querySelector('[data-irz-experiments]');
        const canSend = root.dataset.canSend === '1';
        const pollMs = Math.max(1000, Number(root.dataset.pollMs) || 1000);
        let selectedImei = null;
        let stopped = false;
        let timer = null;
        let rawMode = false;

        function escapeText(value) {
            const span = document.createElement('span');
            span.textContent = value ?? '';
            return span.innerHTML;
        }

        function formatTime(value) {
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('ru-RU', { hour12: false });
        }

        function updateSendState(online) {
            const enabled = canSend && online && Boolean(selectedImei);
            input.disabled = !enabled;
            sendButton.disabled = !enabled;
            labDevice.disabled = !canSend || !online;
            labHex.disabled = !enabled;
            crc.disabled = !enabled;
            append.disabled = !enabled;
            testButton.disabled = !enabled;
        }

        function renderDevices(devices, online) {
            if (devices.length === 1) selectedImei = devices[0].imei;
            if (selectedImei && !devices.some((item) => item.imei === selectedImei)) selectedImei = null;
            devicesNode.replaceChildren();
            labDevice.replaceChildren(new Option('Устройство не выбрано', ''));
            if (!devices.length) {
                const empty = document.createElement('div');
                empty.className = 'p-4 text-center text-muted';
                empty.textContent = online ? 'Нет подключенных устройств' : 'Шлюз недоступен';
                devicesNode.append(empty);
            }
            devices.forEach((device) => {
                labDevice.add(new Option(device.imei, device.imei, false, device.imei === selectedImei));
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `list-group-item list-group-item-action irz-device ${device.imei === selectedImei ? 'active' : ''}`;
                button.innerHTML = `<div class="fw-semibold">IMEI <code>${escapeText(device.imei)}</code></div>`
                    + `<div class="small mt-1">IP ${escapeText(device.ip)} · PORT ${escapeText(device.port)}</div>`
                    + `<div class="small text-muted mt-1">LAST SEEN ${escapeText(device.last_seen_at ? new Date(device.last_seen_at).toLocaleString('ru-RU') : '—')}</div>`;
                button.addEventListener('click', () => { selectedImei = device.imei; refresh(); });
                devicesNode.append(button);
            });
            selectedNode.textContent = rawMode ? 'RAW · ALL DEVICES' : (selectedImei || 'Устройство не выбрано');
            const exportUrl = new URL(root.dataset.exportUrl, window.location.origin);
            if (!rawMode && selectedImei) exportUrl.searchParams.set('imei', selectedImei);
            exportLink.href = exportUrl.toString();
            updateSendState(online);
        }

        function renderLogs(logs) {
            logsNode.replaceChildren();
            if (!logs.length) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="5" class="text-center text-secondary py-5">Лог пуст</td>';
                logsNode.append(row);
                return;
            }
            logs.forEach((item) => {
                const row = document.createElement('tr');
                row.innerHTML = `<td>${escapeText(formatTime(item.created_at))}</td>`
                    + `<td class="${item.direction === 'RX' ? 'irz-dir-rx' : 'irz-dir-tx'}">${escapeText(item.direction)}</td>`
                    + `<td>${escapeText(item.length)}</td><td>${escapeText(item.hex)}</td><td>${escapeText(item.ascii)}</td>`;
                logsNode.append(row);
            });
            const scroller = root.querySelector('[data-irz-log-scroll]');
            scroller.scrollTop = scroller.scrollHeight;
        }

        function renderExperiments(experiments) {
            experimentsNode.replaceChildren();
            if (!experiments.length) {
                const row = document.createElement('tr');
                row.innerHTML = '<td colspan="6" class="text-center text-muted py-4">Экспериментов нет</td>';
                experimentsNode.append(row);
                return;
            }
            experiments.forEach((item) => {
                const row = document.createElement('tr');
                row.innerHTML = `<td>${escapeText(formatTime(item.created_at))}</td><td>${escapeText(item.imei)}</td>`
                    + `<td>${escapeText(item.command_hex)}</td><td>${escapeText(item.response_hex || '—')}</td>`
                    + `<td>${escapeText(item.response_ascii || '—')}</td>`
                    + `<td><span class="badge ${item.success ? 'text-bg-success' : 'text-bg-warning'}">${item.success ? 'RESPONSE' : 'TIMEOUT'}</span></td>`;
                experimentsNode.append(row);
            });
        }

        async function refresh() {
            if (stopped) return;
            if (timer) {
                window.clearTimeout(timer);
                timer = null;
            }
            try {
                const logsUrl = new URL(root.dataset.logsUrl, window.location.origin);
                const experimentsUrl = new URL(root.dataset.experimentsUrl, window.location.origin);
                logsUrl.searchParams.set('limit', '200');
                if (!rawMode && selectedImei) logsUrl.searchParams.set('imei', selectedImei);
                if (selectedImei) experimentsUrl.searchParams.set('imei', selectedImei);
                const [devicesResponse, logsResponse, experimentsResponse] = await Promise.all([
                    fetch(root.dataset.devicesUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' }),
                    fetch(logsUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' }),
                    fetch(experimentsUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' }),
                ]);
                const devicesPayload = await devicesResponse.json();
                const online = devicesResponse.ok && devicesPayload.status === 'online';
                gatewayNode.textContent = online ? 'ONLINE' : 'OFFLINE';
                gatewayNode.className = `badge ${online ? 'text-bg-success' : 'text-bg-danger'}`;
                renderDevices(devicesPayload.devices || [], online);
                if (logsResponse.ok) renderLogs(await logsResponse.json());
                if (experimentsResponse.ok) renderExperiments(await experimentsResponse.json());
                root.querySelector('[data-irz-updated]').textContent = `Обновлено ${new Date().toLocaleTimeString('ru-RU')}`;
            } catch {
                gatewayNode.textContent = 'OFFLINE';
                gatewayNode.className = 'badge text-bg-danger';
                renderDevices([], false);
            } finally {
                if (!stopped) timer = window.setTimeout(refresh, pollMs);
            }
        }

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            messageNode.textContent = '';
            if (!selectedImei) { messageNode.textContent = 'Устройство offline.'; messageNode.className = 'small mt-2 text-danger'; return; }
            sendButton.disabled = true;
            try {
                const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                const response = await fetch(root.dataset.sendUrl, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': csrf },
                    body: JSON.stringify({ imei: selectedImei, hex: input.value }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Не удалось отправить команду.');
                input.value = '';
                messageNode.textContent = `Отправлено ${payload.bytes} байт.`;
                messageNode.className = 'small mt-2 text-success';
                await refresh();
            } catch (error) {
                messageNode.textContent = error.message || 'gateway unavailable';
                messageNode.className = 'small mt-2 text-danger';
            } finally {
                sendButton.disabled = !canSend || !selectedImei;
            }
        });

        labDevice.addEventListener('change', () => {
            selectedImei = labDevice.value || null;
            refresh();
        });

        preset.addEventListener('change', () => {
            if (preset.value) labHex.value = preset.value;
        });

        listenButton.addEventListener('click', () => {
            rawMode = !rawMode;
            listenButton.textContent = rawMode ? 'STOP LISTEN' : 'START LISTEN';
            listenButton.classList.toggle('btn-danger', rawMode);
            listenButton.classList.toggle('btn-outline-light', !rawMode);
            selectedNode.textContent = rawMode ? 'RAW · ALL DEVICES' : (selectedImei || 'Устройство не выбрано');
            refresh();
        });

        testForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            testMessage.textContent = '';
            if (!selectedImei) {
                testMessage.textContent = 'Устройство offline.';
                testMessage.className = 'small mt-2 text-danger';
                return;
            }
            testButton.disabled = true;
            testButton.textContent = 'WAITING…';
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
                const response = await fetch(root.dataset.testUrl, {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': csrfToken },
                    body: JSON.stringify({ imei: selectedImei, hex: labHex.value, crc: crc.value, append: append.value }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Не удалось выполнить тест.');
                testMessage.textContent = payload.success
                    ? `RX: ${payload.response_hex || 'пусто'}`
                    : 'Ответ не получен за 5 секунд.';
                testMessage.className = `small mt-2 ${payload.success ? 'text-success' : 'text-warning'}`;
                await refresh();
            } catch (error) {
                testMessage.textContent = error.message || 'gateway unavailable';
                testMessage.className = 'small mt-2 text-danger';
            } finally {
                testButton.textContent = 'SEND TEST';
                testButton.disabled = !canSend || !selectedImei;
            }
        });

        window.addEventListener('opora:before-navigate', () => {
            stopped = true;
            if (timer) window.clearTimeout(timer);
        }, { once: true });
        refresh();
    }

    document.addEventListener('DOMContentLoaded', boot);
    window.addEventListener('opora:navigated', boot);
    window.OporaIRZ = { init: boot };
})();
