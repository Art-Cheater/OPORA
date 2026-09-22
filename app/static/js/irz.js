(function () {
    function boot() {
        const root = document.querySelector('[data-irz-operator-root]');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';
        const q = (selector) => root.querySelector(selector);
        const devicesNode = q('[data-mercury-devices]');
        const message = q('[data-operation-message]');
        const metrics = q('[data-metrics]');
        const commandsNode = q('[data-command-list]');
        const logNode = q('[data-operation-log]');
        const pollButton = q('[data-device-poll]');
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
        let devices = [], selected = null, commands = [], rawMode = false, stopped = false, timer = null, viewCleared = false, operationBusy = false;

        const endpoint = (suffix = '') => root.dataset.deviceUrlTemplate.replace('DEVICE_ID', selected?.id || '') + suffix;
        const stateClass = (state) => ({ ONLINE: 'success', BUSY: 'warning', ERROR: 'danger' }[state] || 'secondary');
        const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
        const fmtTime = (value) => value ? new Date(value).toLocaleString('ru-RU') : '—';
        const commandTitle = (id) => commands.find((item) => item.id === id)?.title || ({
            serial_and_manufacture: 'Серийный номер и дата выпуска', transformation_ratios: 'Коэффициенты трансформации',
            firmware_version: 'Версия ПО', additional_timeout_multiplier: 'Дополнительный множитель тайм-аута',
            main_timeout_multiplier: 'Основной множитель тайм-аута',
            CONNECT: 'Подключение ATM21', DISCONNECT: 'Отключение ATM21', ATM21_IDENTIFICATION: 'Идентификация ATM21',
            ATM21_HEARTBEAT: 'Heartbeat ATM21', MERCURY_REQUEST: 'Запрос Mercury', MERCURY_RESPONSE: 'Ответ Mercury', UNKNOWN_RAW: 'Неизвестные данные'
        }[id] || id);

        async function api(url, options = {}) {
            const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrf, ...(options.headers || {}) }, ...options });
            const payload = response.status === 204 ? null : await response.json();
            if (!response.ok) throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
            return payload;
        }

        function setMessage(value, kind = 'secondary') {
            message.className = `alert alert-${kind} py-2`;
            message.textContent = value;
        }

        function renderDevices() {
            devicesNode.replaceChildren();
            const emptyState = q('[data-device-empty]');
            emptyState.hidden = devices.length > 0;
            devicesNode.hidden = devices.length === 0;
            if (!devices.length) {
                return;
            }
            devices.forEach((device) => {
                const button = document.createElement('button'); button.type = 'button';
                button.className = `list-group-item list-group-item-action irz-device ${selected?.id === device.id ? 'active' : ''}`;
                const title = document.createElement('div'); title.className = 'd-flex justify-content-between gap-2';
                const name = document.createElement('strong'); name.textContent = device.name;
                const badge = document.createElement('span'); badge.className = `badge text-bg-${stateClass(device.connection_state)}`; badge.textContent = device.connection_state;
                title.append(name, badge);
                const detail = document.createElement('div'); detail.className = 'small text-muted mt-1'; detail.textContent = `IMEI ${device.imei}`;
                const polled = document.createElement('div'); polled.className = 'small text-muted'; polled.textContent = `${device.ip || 'IP неизвестен'} · CSQ ${text(device.csq)}`;
                button.append(title, detail, polled); button.addEventListener('click', () => selectDevice(device.id)); devicesNode.append(button);
            });
        }

        function renderSelected() {
            const panel = q('[data-connection-panel]'); panel.hidden = !selected;
            q('[data-device-title]').textContent = selected?.name || 'Выберите прибор';
            const state = selected?.connection_state || 'OFFLINE';
            const badge = q('[data-device-state]'); badge.textContent = state; badge.className = `badge text-bg-${stateClass(state)}`;
            q('[data-status-dot]').className = `irz-status-dot bg-${stateClass(state)}`;
            q('[data-device-summary]').textContent = selected ? `IMEI ${selected.imei} · ${selected.device_type || 'ATM21'} · ${selected.ip || 'IP неизвестен'} · CSQ ${text(selected.csq)}` : '—';
            if (selected) q('[data-connection-details]').textContent = `IP ${selected.ip || '—'}:${selected.port || '—'}\nПодключён: ${fmtTime(selected.connected_at)}\nПоследний пакет: ${fmtTime(selected.last_seen_at)}\nINT: ${text(selected.interfaces)}\nVER/REV/BLD: ${text(selected.firmware_version)}/${text(selected.firmware_revision)}/${text(selected.firmware_build)}`;
            const atmOnline = Boolean(selected?.online);
            q('[data-atm-status]').textContent = atmOnline ? 'ONLINE' : 'OFFLINE';
            q('[data-atm-status-dot]').className = `irz-status-dot bg-${atmOnline ? 'success' : 'secondary'}`;
            const mercuryOnline = Boolean(selected?.mercury_responding);
            q('[data-mercury-status]').textContent = mercuryOnline ? 'отвечает' : 'нет ответа';
            q('[data-mercury-status-dot]').className = `irz-status-dot bg-${mercuryOnline ? 'success' : 'danger'}`;
            q('[data-mercury-last]').textContent = fmtTime(selected?.last_mercury_seen_at);
            const busy = state === 'BUSY' || operationBusy; pollButton.disabled = !selected || busy || !selected.enabled;
            pollButton.disabled = !selected || busy || !selected.online;
            if (selected) renderPersistedMetrics();
        }

        async function selectDevice(id) {
            selected = devices.find((item) => item.id === id) || null; viewCleared = false; renderDevices(); renderSelected();
            if (!selected) return;
            try {
                [commands] = await Promise.all([api(endpoint('/commands')), refreshLog()]);
                renderCommands();
            } catch (error) { setMessage(error.message, 'danger'); }
        }

        function renderCommands() {
            commandsNode.replaceChildren();
            commands.forEach((command) => {
                const col = document.createElement('div'); col.className = 'col-md-6 col-xxl-4';
                const button = document.createElement('button'); button.type = 'button'; button.className = `btn w-100 text-start ${command.available ? 'btn-outline-primary' : 'btn-outline-secondary'}`; button.disabled = !command.available || !selected?.online || operationBusy || selected?.connection_state === 'BUSY';
                const title = document.createElement('strong'); title.textContent = command.title;
                const detail = document.createElement('small'); detail.className = 'd-block text-muted mt-1'; detail.textContent = command.available ? command.description : command.limitation;
                button.append(title, detail); if (command.available) button.addEventListener('click', () => executeCommand(command)); col.append(button); commandsNode.append(col);
            });
        }

        function renderMetrics(results) {
            metrics.replaceChildren();
            Object.entries(results || {}).forEach(([id, item]) => {
                const spec = commands.find((value) => value.id === id);
                const col = document.createElement('div'); col.className = 'col-md-6 col-xxl-4';
                const card = document.createElement('div'); card.className = 'border rounded p-3 h-100';
                const label = document.createElement('div'); label.className = 'small text-muted'; label.textContent = spec?.title || commandTitle(id);
                const value = document.createElement('div'); value.className = 'irz-result-value mt-1'; value.textContent = formatResult(id, item.data);
                card.append(label, value); col.append(card); metrics.append(col);
            });
            if (!metrics.children.length) metrics.textContent = 'Данные не получены.';
        }

        function formatResult(id, value) {
            if (id === 'serial_and_manufacture' && value) return `Серийный № ${text(value.serial_number)} · дата выпуска ${value.date_of_manufacture ? new Date(`${value.date_of_manufacture}T00:00:00`).toLocaleDateString('ru-RU') : '—'}`;
            if (id === 'transformation_ratios' && value) return `Напряжение: ${text(value.voltage)} · ток: ${text(value.current)}`;
            return typeof value === 'object' ? JSON.stringify(value) : text(value);
        }

        function renderPersistedMetrics() {
            const values = selected?.last_values || {};
            const saved = {};
            if (values.serial_number || values.date_of_manufacture) saved.serial_and_manufacture = { data: values };
            if (values.firmware_version) saved.firmware_version = { data: values.firmware_version };
            if (values.transformation_ratios) saved.transformation_ratios = { data: values.transformation_ratios };
            renderMetrics(saved);
        }

        async function executeCommand(command) {
            if (command.dangerous && !window.confirm(`Опасная команда: ${command.title}\nУстройство: ${selected.name}\nПродолжить?`)) return;
            setBusy(true, `Выполняется: ${command.title}…`);
            try {
                const url = root.dataset.commandUrlTemplate.replace('DEVICE_ID', selected.id).replace('COMMAND_ID', command.id);
                const result = await api(url, { method: 'POST', body: JSON.stringify({ confirm: command.dangerous === true }) });
                renderMetrics({ [command.id]: result }); setMessage(`${command.title}: выполнено за ${result.duration_ms} мс`, 'success');
            } catch (error) { setMessage(error.message, 'danger'); } finally { setBusy(false); await reload(); }
        }

        function setBusy(busy, label) {
            operationBusy = busy;
            if (selected && busy) selected.connection_state = 'BUSY';
            pollButton.disabled = busy || !selected; if (label) setMessage(label, 'info'); renderSelected(); renderCommands();
        }

        async function refreshLog() {
            if (!selected || viewCleared) { logNode.innerHTML = '<div class="p-4 text-muted text-center">Журнал пуст</div>'; return; }
            const url = new URL(endpoint('/exchange-log'), window.location.origin); url.searchParams.set('limit', '100'); const filter = q('[data-log-filter]').value;
            let entries = await api(url);
            if (!filter) entries = entries.filter((entry) => !['RX', 'TX'].includes(entry.operation));
            if (filter === 'ATM21') entries = entries.filter((entry) => /ATM21|CONNECT|DISCONNECT/.test(entry.command_id) && entry.command_id !== 'ATM21_HEARTBEAT');
            if (filter === 'HEARTBEAT') entries = entries.filter((entry) => entry.command_id === 'ATM21_HEARTBEAT');
            if (filter === 'ERROR') entries = entries.filter((entry) => entry.status === 'ERROR' || entry.status === 'TIMEOUT');
            if (filter === 'RAW') rawMode = true;
            logNode.replaceChildren();
            entries.forEach((entry) => {
                const row = document.createElement('div'); row.className = `irz-operation irz-operation-${entry.status.toLowerCase()}`;
                const head = document.createElement('div'); head.className = 'd-flex justify-content-between gap-2';
                const summary = document.createElement('strong'); summary.textContent = `${fmtTime(entry.created_at)} ${entry.status === 'SUCCESS' ? '✓' : '✕'} ${commandTitle(entry.command_id)}`;
                const duration = document.createElement('span'); duration.className = 'text-muted'; duration.textContent = entry.duration_ms === null ? '' : `${entry.duration_ms} мс`; head.append(summary, duration);
                const body = document.createElement('pre'); body.className = 'mb-0 mt-1';
                const crc = entry.crc_ok === true ? 'OK' : (entry.crc_ok === false ? 'ERROR' : '—');
                const rawText = `TX: ${text(entry.tx_raw)}\nRX: ${text(entry.rx_raw)}\nCRC: ${crc}\nDuration: ${entry.duration_ms === null ? '—' : `${entry.duration_ms} ms`}`;
                body.textContent = rawMode || filter === 'RAW' ? rawText : (entry.error_message || formatResult(entry.command_id, entry.result));
                row.append(head, body);
                if (rawMode || filter === 'RAW') { const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'btn btn-sm btn-link px-0'; copy.textContent = 'Копировать RAW'; copy.addEventListener('click', () => navigator.clipboard?.writeText(rawText)); row.append(copy); }
                logNode.append(row);
            });
            if (!entries.length) logNode.innerHTML = '<div class="p-4 text-muted text-center">Журнал пуст</div>';
        }

        async function reload() {
            devices = await api(root.dataset.mercuryDevicesUrl); if (selected) selected = devices.find((item) => item.id === selected.id) || null;
            renderDevices(); renderSelected(); if (selected) await refreshLog();
        }

        pollButton.addEventListener('click', async () => {
            setBusy(true, 'Выполняется комплексный опрос…');
            try { const result = await api(endpoint('/poll'), { method: 'POST', body: '{}' }); renderMetrics(result.results); setMessage(result.partial ? `Опрос завершён частично: ошибок ${result.errors.length}` : 'Опрос успешно завершён.', result.partial ? 'warning' : 'success'); }
            catch (error) { setMessage(error.message, 'danger'); } finally { setBusy(false); await reload(); }
        });
        q('[data-log-filter]').addEventListener('change', () => { viewCleared = false; refreshLog(); });
        root.querySelectorAll('[data-log-mode]').forEach((button) => button.addEventListener('click', () => { rawMode = button.dataset.logMode === 'raw'; root.querySelectorAll('[data-log-mode]').forEach((item) => item.classList.toggle('active', item === button)); refreshLog(); }));
        q('[data-clear-view]').addEventListener('click', () => { viewCleared = true; refreshLog(); });

        async function tick() { try { await reload(); } catch (error) { devices = []; selected = null; renderDevices(); renderSelected(); setMessage(`Не удалось загрузить устройства: ${error.message}`, 'danger'); } finally { if (!stopped) timer = window.setTimeout(tick, Math.max(1000, Number(root.dataset.pollMs) || 1000)); } }
        window.addEventListener('opora:before-navigate', () => { stopped = true; if (timer) window.clearTimeout(timer); }, { once: true }); tick();
    }
    document.addEventListener('DOMContentLoaded', boot); window.addEventListener('opora:navigated', boot); window.OporaIRZOperator = { init: boot };
})();
