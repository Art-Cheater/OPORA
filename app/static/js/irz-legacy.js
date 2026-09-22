(function () {
    function boot() {
        const root = document.querySelector('[data-irz-legacy-root]');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';
        const q = (selector) => root.querySelector(selector);
        const devicesNode = q('[data-irz-devices]');
        const logsNode = q('[data-irz-logs]');
        const gatewayNode = q('[data-irz-gateway]');
        const selectedNode = q('[data-irz-selected]');
        const labDevice = q('[data-irz-lab-device]');
        const canSend = root.dataset.canSend === '1';
        const pollMs = Math.max(1000, Number(root.dataset.pollMs) || 1000);
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
        let selectedImei = null, rawMode = false, stopped = false, timer = null, started = false;

        const escapeText = (value) => { const span = document.createElement('span'); span.textContent = value ?? ''; return span.innerHTML; };
        const formatTime = (value) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('ru-RU', { hour12: false }); };

        function updateState(online) {
            const enabled = canSend && online && Boolean(selectedImei);
            [q('[data-irz-hex]'), q('[data-irz-send]'), q('[data-irz-lab-hex]'), q('[data-irz-crc]'), q('[data-irz-append]'), q('[data-irz-test-send]')].forEach((node) => { node.disabled = !enabled; });
            labDevice.disabled = !canSend || !online;
        }

        function renderDevices(devices, online) {
            if (devices.length === 1) selectedImei = devices[0].imei;
            if (selectedImei && !devices.some((item) => item.imei === selectedImei)) selectedImei = null;
            devicesNode.replaceChildren(); labDevice.replaceChildren(new Option('Устройство не выбрано', ''));
            if (!devices.length) { const empty = document.createElement('div'); empty.className = 'p-4 text-center text-muted'; empty.textContent = online ? 'Нет подключенных ATM21' : 'Modem-sniffer недоступен'; devicesNode.append(empty); }
            devices.forEach((device) => {
                labDevice.add(new Option(device.imei, device.imei, false, device.imei === selectedImei));
                const button = document.createElement('button'); button.type = 'button'; button.className = `list-group-item list-group-item-action irz-device ${device.imei === selectedImei ? 'active' : ''}`;
                button.innerHTML = `<div class="fw-semibold">IMEI <code>${escapeText(device.imei)}</code></div><div class="small">${escapeText(device.ip)}:${escapeText(device.port)}</div>`;
                button.addEventListener('click', () => { selectedImei = device.imei; refresh(); }); devicesNode.append(button);
            });
            selectedNode.textContent = rawMode ? 'RAW · ALL DEVICES' : (selectedImei || 'Устройство не выбрано');
            const exportUrl = new URL(root.dataset.exportUrl, window.location.origin); if (!rawMode && selectedImei) exportUrl.searchParams.set('imei', selectedImei); q('[data-irz-export]').href = exportUrl;
            updateState(online);
        }

        function renderLogs(logs) {
            logsNode.replaceChildren();
            logs.forEach((item) => { const row = document.createElement('tr'); row.innerHTML = `<td>${escapeText(formatTime(item.created_at))}</td><td class="${item.direction === 'RX' ? 'irz-dir-rx' : 'irz-dir-tx'}">${escapeText(item.direction)}</td><td>${escapeText(item.length)}</td><td>${escapeText(item.hex)}</td><td>${escapeText(item.ascii)}</td>`; logsNode.append(row); });
            if (!logs.length) logsNode.innerHTML = '<tr><td colspan="5" class="text-center text-secondary py-5">Лог пуст</td></tr>';
            q('[data-irz-log-scroll]').scrollTop = q('[data-irz-log-scroll]').scrollHeight;
        }

        function renderExperiments(items) {
            const node = q('[data-irz-experiments]'); node.replaceChildren();
            items.forEach((item) => { const row = document.createElement('tr'); row.innerHTML = `<td>${escapeText(formatTime(item.created_at))}</td><td>${escapeText(item.imei)}</td><td>${escapeText(item.command_hex)}</td><td>${escapeText(item.response_hex || '—')}</td><td>${escapeText(item.response_ascii || '—')}</td><td>${item.success ? 'RESPONSE' : 'TIMEOUT'}</td>`; node.append(row); });
            if (!items.length) node.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Экспериментов нет</td></tr>';
        }

        async function refresh() {
            if (stopped) return;
            if (timer) window.clearTimeout(timer);
            try {
                const logsUrl = new URL(root.dataset.logsUrl, window.location.origin); logsUrl.searchParams.set('limit', '200'); if (!rawMode && selectedImei) logsUrl.searchParams.set('imei', selectedImei);
                const experimentsUrl = new URL(root.dataset.experimentsUrl, window.location.origin); if (selectedImei) experimentsUrl.searchParams.set('imei', selectedImei);
                const [deviceResponse, logResponse, experimentResponse] = await Promise.all([fetch(root.dataset.devicesUrl, { cache: 'no-store' }), fetch(logsUrl, { cache: 'no-store' }), fetch(experimentsUrl, { cache: 'no-store' })]);
                const devicePayload = await deviceResponse.json(); const online = deviceResponse.ok && devicePayload.status === 'online';
                gatewayNode.textContent = online ? 'ONLINE' : 'OFFLINE'; gatewayNode.className = `badge ${online ? 'text-bg-success' : 'text-bg-danger'}`;
                renderDevices(devicePayload.devices || [], online); if (logResponse.ok) renderLogs(await logResponse.json()); if (experimentResponse.ok) renderExperiments(await experimentResponse.json()); q('[data-irz-updated]').textContent = `Обновлено ${new Date().toLocaleTimeString('ru-RU')}`;
            } catch (error) { gatewayNode.textContent = 'OFFLINE'; gatewayNode.className = 'badge text-bg-danger'; renderDevices([], false); q('[data-irz-message]').textContent = error.message; }
            finally { if (!stopped) timer = window.setTimeout(refresh, pollMs); }
        }

        q('[data-irz-send-form]').addEventListener('submit', async (event) => {
            event.preventDefault(); const message = q('[data-irz-message]');
            try { const response = await fetch(root.dataset.sendUrl, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ imei: selectedImei, hex: q('[data-irz-hex]').value }) }); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || 'Ошибка отправки'); message.className = 'small mt-2 text-success'; message.textContent = `Отправлено ${payload.bytes} байт`; await refresh(); }
            catch (error) { message.className = 'small mt-2 text-danger'; message.textContent = error.message; }
        });
        labDevice.addEventListener('change', () => { selectedImei = labDevice.value || null; refresh(); });
        q('[data-irz-preset]').addEventListener('change', (event) => { if (event.target.value) q('[data-irz-lab-hex]').value = event.target.value; });
        q('[data-irz-listen]').addEventListener('click', (event) => { rawMode = !rawMode; event.currentTarget.textContent = rawMode ? 'STOP LISTEN' : 'START LISTEN'; refresh(); });
        q('[data-irz-test-form]').addEventListener('submit', async (event) => {
            event.preventDefault(); const button = q('[data-irz-test-send]'); const message = q('[data-irz-test-message]'); button.disabled = true; button.textContent = 'WAITING…';
            try { const response = await fetch(root.dataset.testUrl, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ imei: selectedImei, hex: q('[data-irz-lab-hex]').value, crc: q('[data-irz-crc]').value, append: q('[data-irz-append]').value }) }); const payload = await response.json(); if (!response.ok) throw new Error(payload.error || 'Ошибка теста'); message.className = `small mt-2 ${payload.success ? 'text-success' : 'text-warning'}`; message.textContent = payload.success ? `RX: ${payload.response_hex}` : 'Ответ не получен за 5 секунд'; await refresh(); }
            catch (error) { message.className = 'small mt-2 text-danger'; message.textContent = error.message; }
            finally { button.textContent = 'SEND TEST'; button.disabled = !canSend || !selectedImei; }
        });
        function start() { if (started || stopped) return; started = true; refresh(); }
        document.getElementById('irzLegacyTab')?.addEventListener('shown.bs.tab', start);
        if (document.getElementById('irzLegacyTab')?.classList.contains('active')) start();
        window.addEventListener('opora:before-navigate', () => { stopped = true; if (timer) window.clearTimeout(timer); }, { once: true });
    }
    document.addEventListener('DOMContentLoaded', boot); window.addEventListener('opora:navigated', boot); window.OporaIRZLegacy = { init: boot };
})();
