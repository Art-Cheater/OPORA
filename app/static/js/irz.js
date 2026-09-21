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
        const canSend = root.dataset.canSend === '1';
        const pollMs = Math.max(1000, Number(root.dataset.pollMs) || 1000);
        let selectedImei = null;
        let stopped = false;
        let timer = null;

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
        }

        function renderDevices(devices, online) {
            if (devices.length === 1) selectedImei = devices[0].imei;
            if (selectedImei && !devices.some((item) => item.imei === selectedImei)) selectedImei = null;
            devicesNode.replaceChildren();
            if (!devices.length) {
                const empty = document.createElement('div');
                empty.className = 'p-4 text-center text-muted';
                empty.textContent = online ? 'Нет подключенных устройств' : 'Шлюз недоступен';
                devicesNode.append(empty);
            }
            devices.forEach((device) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `list-group-item list-group-item-action irz-device ${device.imei === selectedImei ? 'active' : ''}`;
                button.innerHTML = `<div class="fw-semibold">IMEI <code>${escapeText(device.imei)}</code></div>`
                    + `<div class="small mt-1">IP ${escapeText(device.ip)} · PORT ${escapeText(device.port)}</div>`
                    + `<div class="small text-muted mt-1">LAST SEEN ${escapeText(device.last_seen_at ? new Date(device.last_seen_at).toLocaleString('ru-RU') : '—')}</div>`;
                button.addEventListener('click', () => { selectedImei = device.imei; refresh(); });
                devicesNode.append(button);
            });
            selectedNode.textContent = selectedImei || 'Устройство не выбрано';
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

        async function refresh() {
            if (stopped) return;
            if (timer) {
                window.clearTimeout(timer);
                timer = null;
            }
            try {
                const logsUrl = new URL(root.dataset.logsUrl, window.location.origin);
                logsUrl.searchParams.set('limit', '200');
                if (selectedImei) logsUrl.searchParams.set('imei', selectedImei);
                const [devicesResponse, logsResponse] = await Promise.all([
                    fetch(root.dataset.devicesUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' }),
                    fetch(logsUrl, { headers: { Accept: 'application/json' }, cache: 'no-store' }),
                ]);
                const devicesPayload = await devicesResponse.json();
                const online = devicesResponse.ok && devicesPayload.status === 'online';
                gatewayNode.textContent = online ? 'ONLINE' : 'OFFLINE';
                gatewayNode.className = `badge ${online ? 'text-bg-success' : 'text-bg-danger'}`;
                renderDevices(devicesPayload.devices || [], online);
                if (logsResponse.ok) renderLogs(await logsResponse.json());
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
