/* Realtime controller status without a page reload. */
(function () {
    function valueBadge(value, stale) {
        if (stale || value === undefined || value === null) {
            return '<span class="text-muted">Нет данных</span>';
        }
        return Number(value) === 1 || value === true
            ? '<span class="badge text-bg-success">ВКЛ</span>'
            : '<span class="badge text-bg-secondary">ВЫКЛ</span>';
    }

    function formatDate(value) {
        if (!value) return '—';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('ru-RU');
    }

    function commandMessage(active, latest) {
        if (active) {
            return active.status === 'sent'
                ? '<span class="spinner-border spinner-border-sm me-2"></span>Ожидание платы…'
                : '<span class="spinner-border spinner-border-sm me-2"></span>Отправка команды…';
        }
        if (latest?.confirmation === 'confirmed') return 'Выполнено: состояние подтверждено платой.';
        if (latest?.confirmation === 'waiting_state') return 'Команда подтверждена. Ожидание нового state от платы.';
        if (latest?.confirmation === 'mismatch') return 'Команда подтверждена, но state не соответствует требуемому состоянию.';
        if (latest?.status === 'timeout') return 'Таймаут ожидания ACK от платы.';
        if (latest?.status === 'failed') return `Ошибка платы: ${latest.error || 'команда не выполнена'}.`;
        return 'Нет выполняемых команд.';
    }

    function renderTelemetry(container, telemetry) {
        container.replaceChildren();
        const entries = Object.entries(telemetry || {});
        if (!entries.length) {
            container.textContent = 'Нет данных';
            container.classList.add('text-muted');
            return;
        }
        container.classList.remove('text-muted');
        entries.forEach(([key, value]) => {
            const row = document.createElement('div');
            const label = document.createElement('dt');
            const data = document.createElement('dd');
            label.className = 'd-inline';
            data.className = 'd-inline';
            label.textContent = `${key}:`;
            data.textContent = ` ${typeof value === 'object' ? JSON.stringify(value) : value}`;
            row.append(label, data);
            container.append(row);
        });
    }

    function renderValues(container, groups) {
        container.replaceChildren();
        const entries = Object.entries(groups?.inputs || {}).concat(Object.entries(groups?.raw || {}));
        if (!entries.length) {
            container.textContent = 'Нет данных';
            container.classList.add('text-muted');
            return;
        }
        container.classList.remove('text-muted');
        entries.forEach(([key, value]) => {
            const row = document.createElement('div');
            const label = document.createElement('dt');
            const data = document.createElement('dd');
            label.className = 'd-inline';
            data.className = 'd-inline';
            label.textContent = `${key}:`;
            data.textContent = ` ${typeof value === 'object' ? JSON.stringify(value) : value}`;
            row.append(label, data);
            container.append(row);
        });
    }

    function renderCard(card, device, commandsEnabled, canManage) {
        const stale = Boolean(device.state_stale);
        const outputs = device.actual_state?.outputs || {};
        const desired = device.desired_state?.outputs || {};
        const online = card.querySelector('[data-device-online]');
        online.textContent = device.connection_state === 'online' ? 'ONLINE' : 'OFFLINE';
        online.className = `badge ${device.connection_state === 'online' ? 'text-bg-success' : 'text-bg-secondary'}`;
        card.querySelector('[data-last-seen]').textContent = formatDate(device.last_seen_at);
        card.querySelector('[data-last-state]').textContent = formatDate(device.last_state_at);
        card.querySelector('[data-last-ip]').textContent = device.last_ip || '—';
        ['C6', 'C7', 'C8'].forEach((relay) => {
            card.querySelector(`[data-output="${relay}"]`).innerHTML = valueBadge(outputs[relay], stale);
            card.querySelector(`[data-desired="${relay}"]`).textContent = desired[relay] ?? '—';
        });
        renderTelemetry(card.querySelector('[data-telemetry]'), device.telemetry);
        renderValues(card.querySelector('[data-raw-inputs-list]'), device.actual_state);

        const status = card.querySelector('[data-command-status]');
        status.innerHTML = commandMessage(device.active_command, device.latest_command);
        status.className = `alert py-2 mt-3 mb-3 ${device.active_command ? 'alert-warning' : device.latest_command?.confirmation === 'mismatch' || device.latest_command?.status === 'failed' || device.latest_command?.status === 'timeout' ? 'alert-danger' : 'alert-light'}`;

        if (!canManage) return;
        const locked = !device.can_send_command;
        const reason = card.querySelector('[data-command-block-reason]');
        reason.textContent = device.command_block_reason || '';
        reason.hidden = !device.command_block_reason;
        card.querySelectorAll('[data-device-command-form] button').forEach((button) => {
            button.disabled = locked;
        });
    }

    function boot() {
        const root = document.querySelector('[data-devices-root]');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';
        const canManage = root.dataset.canManage === '1';
        let stopped = false;
        let timer = null;

        async function refresh() {
            if (stopped) return;
            try {
                const response = await fetch(root.dataset.statusUrl, {
                    headers: { Accept: 'application/json' },
                    cache: 'no-store',
                });
                if (!response.ok) return;
                const data = await response.json();
                data.devices.forEach((device) => {
                    const card = root.querySelector(`[data-device-id="${device.device_id}"]`);
                    if (card) renderCard(card, device, data.commands_enabled, canManage);
                });
            } catch {
                /* A transient network failure must not change displayed actual state. */
            } finally {
                if (!stopped) timer = window.setTimeout(refresh, 1000);
            }
        }

        root.querySelectorAll('[data-device-command-form]').forEach((form) => {
            form.addEventListener('submit', async (event) => {
                event.preventDefault();
                if (form.dataset.confirmMessage && !window.confirm(form.dataset.confirmMessage)) return;
                const card = form.closest('[data-device-card]');
                card?.querySelectorAll('[data-device-command-form] button').forEach((button) => { button.disabled = true; });
                try {
                    const response = await fetch(form.action, {
                        method: 'POST',
                        body: new FormData(form),
                        headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
                    });
                    if (!response.ok) {
                        const body = await response.text();
                        throw new Error(body || 'Не удалось поставить команду в очередь.');
                    }
                    await refresh();
                } catch (error) {
                    const status = card?.querySelector('[data-command-status]');
                    if (status) {
                        status.className = 'alert alert-danger py-2 mt-3 mb-3';
                        status.textContent = error.message || 'Не удалось поставить команду в очередь.';
                    }
                    await refresh();
                }
            });
        });

        const destroy = () => {
            stopped = true;
            if (timer) window.clearTimeout(timer);
        };
        window.addEventListener('opora:before-navigate', destroy, { once: true });
        refresh();
    }

    document.addEventListener('DOMContentLoaded', boot);
    window.addEventListener('opora:navigated', boot);
    window.OporaDevices = { init: boot };
})();
