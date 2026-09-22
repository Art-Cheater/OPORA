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
        let devices = [], selected = null, commands = [], rawMode = false, stopped = false, timer = null, viewCleared = false;

        const endpoint = (suffix = '') => root.dataset.deviceUrlTemplate.replace('DEVICE_ID', selected?.id || '') + suffix;
        const stateClass = (state) => ({ CONNECTED: 'success', BUSY: 'warning', ERROR: 'danger' }[state] || 'secondary');
        const text = (value) => value === null || value === undefined || value === '' ? '—' : String(value);
        const fmtTime = (value) => value ? new Date(value).toLocaleString('ru-RU') : '—';

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
                const detail = document.createElement('div'); detail.className = 'small text-muted mt-1'; detail.textContent = `${device.model} · адрес ${device.network_address}`;
                const polled = document.createElement('div'); polled.className = 'small text-muted'; polled.textContent = `Опрос: ${fmtTime(device.last_polled_at)}`;
                button.append(title, detail, polled); button.addEventListener('click', () => selectDevice(device.id)); devicesNode.append(button);
            });
        }

        function renderSelected() {
            const panel = q('[data-connection-panel]'); panel.hidden = !selected;
            q('[data-device-title]').textContent = selected?.name || 'Выберите прибор';
            const state = selected?.connection_state || 'DISCONNECTED';
            const badge = q('[data-device-state]'); badge.textContent = state; badge.className = `badge text-bg-${stateClass(state)}`;
            q('[data-status-dot]').className = `irz-status-dot bg-${stateClass(state)}`;
            q('[data-device-summary]').textContent = selected ? `${selected.model} · ${selected.serial_number ? `№ ${selected.serial_number} · ` : ''}${selected.transport_type === 'TCP' ? `TCP ${selected.host}:${selected.port}` : `${selected.serial_port} @ ${selected.baudrate}`} · ответ ${text(selected.last_latency_ms)} мс` : '—';
            if (selected) q('[data-connection-details]').textContent = selected.transport_type === 'TCP' ? `TCP/IP ${selected.host}:${selected.port}\nСетевой адрес: ${selected.network_address}` : `Serial ${selected.serial_port}\n${selected.baudrate} бод · адрес ${selected.network_address}`;
            const busy = state === 'BUSY'; pollButton.disabled = !selected || busy || !selected.enabled;
            root.querySelectorAll('[data-device-action]').forEach((button) => { button.disabled = !selected || busy || (root.dataset.canControl !== '1' && button.dataset.deviceAction !== 'test'); });
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
                const button = document.createElement('button'); button.type = 'button'; button.className = `btn w-100 text-start ${command.available ? 'btn-outline-primary' : 'btn-outline-secondary'}`; button.disabled = !command.available || selected?.connection_state === 'BUSY';
                const title = document.createElement('strong'); title.textContent = command.title;
                const detail = document.createElement('small'); detail.className = 'd-block text-muted mt-1'; detail.textContent = command.available ? `${command.category} · ${command.mercury_command}` : command.limitation;
                button.append(title, detail); if (command.available) button.addEventListener('click', () => executeCommand(command)); col.append(button); commandsNode.append(col);
            });
        }

        function renderMetrics(results) {
            metrics.replaceChildren();
            Object.entries(results || {}).forEach(([id, item]) => {
                const spec = commands.find((value) => value.id === id);
                const col = document.createElement('div'); col.className = 'col-md-6 col-xxl-4';
                const card = document.createElement('div'); card.className = 'border rounded p-3 h-100';
                const label = document.createElement('div'); label.className = 'small text-muted'; label.textContent = spec?.title || id;
                const value = document.createElement('pre'); value.className = 'irz-result mb-0 mt-2'; value.textContent = JSON.stringify(item.data, null, 2);
                card.append(label, value); col.append(card); metrics.append(col);
            });
            if (!metrics.children.length) metrics.textContent = 'Данные не получены.';
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
            if (selected) selected.connection_state = busy ? 'BUSY' : selected.connection_state;
            pollButton.disabled = busy || !selected; if (label) setMessage(label, 'info'); renderSelected(); renderCommands();
        }

        async function refreshLog() {
            if (!selected || viewCleared) { logNode.innerHTML = '<div class="p-4 text-muted text-center">Журнал пуст</div>'; return; }
            const url = new URL(endpoint('/exchange-log'), window.location.origin); url.searchParams.set('limit', '100'); const filter = q('[data-log-filter]').value; if (['SUCCESS', 'ERROR', 'TIMEOUT'].includes(filter)) url.searchParams.set('status', filter);
            const entries = await api(url); logNode.replaceChildren();
            entries.forEach((entry) => {
                const row = document.createElement('div'); row.className = `irz-operation irz-operation-${entry.status.toLowerCase()}`;
                const head = document.createElement('div'); head.className = 'd-flex justify-content-between gap-2';
                const summary = document.createElement('strong'); summary.textContent = `${fmtTime(entry.created_at)} ${entry.status === 'SUCCESS' ? '←' : '✕'} ${entry.command_id}`;
                const duration = document.createElement('span'); duration.className = 'text-muted'; duration.textContent = entry.duration_ms === null ? '' : `${entry.duration_ms} мс`; head.append(summary, duration);
                const body = document.createElement('pre'); body.className = 'mb-0 mt-1';
                const rawText = filter === 'RAW_TX' ? `TX ${text(entry.tx_raw)}` : (filter === 'RAW_RX' ? `RX ${text(entry.rx_raw)}` : `TX ${text(entry.tx_raw)}\nRX ${text(entry.rx_raw)}`);
                body.textContent = rawMode || filter.startsWith('RAW_') ? rawText : (entry.error_message || JSON.stringify(entry.result, null, 2));
                row.append(head, body);
                if (rawMode || filter.startsWith('RAW_')) { const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'btn btn-sm btn-link px-0'; copy.textContent = 'Копировать RAW'; copy.addEventListener('click', () => navigator.clipboard?.writeText(rawText)); row.append(copy); }
                logNode.append(row);
            });
            if (!entries.length) logNode.innerHTML = '<div class="p-4 text-muted text-center">Журнал пуст</div>';
        }

        async function reload() {
            devices = await api(root.dataset.mercuryDevicesUrl); if (selected) selected = devices.find((item) => item.id === selected.id) || null;
            renderDevices(); renderSelected(); if (selected) await refreshLog();
        }

        root.querySelectorAll('[data-device-action]').forEach((button) => button.addEventListener('click', async () => {
            const action = button.dataset.deviceAction; setBusy(true, `${button.textContent.trim()}…`);
            try { await api(endpoint(`/${action}`), { method: 'POST', body: '{}' }); setMessage('Операция выполнена.', 'success'); }
            catch (error) { setMessage(error.message, 'danger'); } finally { setBusy(false); await reload(); }
        }));
        pollButton.addEventListener('click', async () => {
            setBusy(true, 'Выполняется комплексный опрос…');
            try { const result = await api(endpoint('/poll'), { method: 'POST', body: '{}' }); renderMetrics(result.results); setMessage(result.partial ? `Опрос завершён частично: ошибок ${result.errors.length}` : 'Опрос успешно завершён.', result.partial ? 'warning' : 'success'); }
            catch (error) { setMessage(error.message, 'danger'); } finally { setBusy(false); await reload(); }
        });
        q('[data-log-filter]').addEventListener('change', () => { viewCleared = false; refreshLog(); });
        root.querySelectorAll('[data-log-mode]').forEach((button) => button.addEventListener('click', () => { rawMode = button.dataset.logMode === 'raw'; root.querySelectorAll('[data-log-mode]').forEach((item) => item.classList.toggle('active', item === button)); refreshLog(); }));
        q('[data-clear-view]').addEventListener('click', () => { viewCleared = true; refreshLog(); });

        const dialog = q('[data-device-dialog]'); const form = q('[data-device-form]');
        function toggleTransport() { if (!form) return; const serial = form.elements.transport_type.value === 'SERIAL'; root.querySelectorAll('[data-field-serial]').forEach((node) => { node.hidden = !serial; }); root.querySelectorAll('[data-field-tcp]').forEach((node) => { node.hidden = serial; }); }
        function openForm(device = null) { form.reset(); form.dataset.deviceId = device?.id || ''; form.elements.name.value = device?.name || ''; form.elements.model.value = device?.model || 'Mercury V2'; form.elements.network_address.value = device?.network_address || ''; form.elements.transport_type.value = device?.transport_type || 'TCP'; form.elements.host.value = device?.host || ''; form.elements.port.value = device?.port || ''; form.elements.serial_port.value = device?.serial_port || ''; form.elements.baudrate.value = device?.baudrate || 9600; form.elements.timeout.value = device?.connection_params?.timeout || 5; form.elements.enabled.checked = device?.enabled ?? true; toggleTransport(); dialog.showModal(); }
        q('[data-device-new]')?.addEventListener('click', () => openForm()); q('[data-device-empty-add]')?.addEventListener('click', () => openForm()); q('[data-device-edit]')?.addEventListener('click', () => openForm(selected)); root.querySelectorAll('[data-dialog-close]').forEach((button) => button.addEventListener('click', () => dialog.close())); form?.elements.transport_type.addEventListener('change', toggleTransport);
        form?.addEventListener('submit', async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(form)); values.enabled = form.elements.enabled.checked; try { const id = form.dataset.deviceId; await api(id ? root.dataset.deviceUrlTemplate.replace('DEVICE_ID', id) : root.dataset.mercuryDevicesUrl, { method: id ? 'PUT' : 'POST', body: JSON.stringify(values) }); dialog.close(); await reload(); } catch (error) { q('[data-form-error]').textContent = error.message; } });

        async function tick() { try { await reload(); } catch (error) { devices = []; selected = null; renderDevices(); renderSelected(); setMessage(`Не удалось загрузить устройства: ${error.message}`, 'danger'); } finally { if (!stopped) timer = window.setTimeout(tick, Math.max(1000, Number(root.dataset.pollMs) || 1000)); } }
        window.addEventListener('opora:before-navigate', () => { stopped = true; if (timer) window.clearTimeout(timer); }, { once: true }); tick();
    }
    document.addEventListener('DOMContentLoaded', boot); window.addEventListener('opora:navigated', boot); window.OporaIRZOperator = { init: boot };
})();
