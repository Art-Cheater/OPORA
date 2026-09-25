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

    const previousPins = new Map();
    const changedUntil = new Map();
    function renderDiagnostics(card, device) {
        const stale = Boolean(device.state_stale);
        const deviceKey = card.dataset.deviceId;
        const known = previousPins.has(deviceKey);
        const previous = previousPins.get(deviceKey) || {};
        const next = {};
        ['U2', 'U3'].forEach((bank) => {
            const bits = device.actual_state?.raw_bits?.[bank] || {};
            const changes = device.actual_state?.raw_bit_changes?.[bank] || {};
            for (let bit = 0; bit < 8; bit += 1) {
                const row = card.querySelector(`[data-raw-bit="${bank}.${bit}"]`);
                if (!row) continue;
                const key = `${bank}.${bit}`;
                const value = bits[String(bit)];
                const cell = row.querySelector('[data-raw-value]');
                const changeCell = row.querySelector('[data-raw-change]');
                if (stale || value === undefined) {
                    cell.textContent = '—';
                    changeCell.textContent = '';
                } else {
                    next[key] = Number(value);
                    cell.textContent = String(Number(value));
                    const change = changes[String(bit)];
                    changeCell.textContent = change ? `${change.from}→${change.to} ${formatDate(change.at)}` : '';
                    const highlightKey = `${deviceKey}:${key}`;
                    if (known && previous[key] !== undefined && previous[key] !== next[key]) {
                        changedUntil.set(highlightKey, Date.now() + 2500);
                    }
                    if ((changedUntil.get(highlightKey) || 0) > Date.now()) row.classList.add('is-changed');
                    else row.classList.remove('is-changed');
                }
            }
        });
        if (!stale) previousPins.set(deviceKey, next);
        ['U2', 'U3'].forEach((bank) => {
            const live = card.querySelector(`[data-live-bank="${bank}"]`);
            if (!live) return;
            const hex = device.actual_state?.raw?.[bank];
            live.textContent = stale || !hex ? '—' : String(hex);
        });
        card.querySelectorAll('[data-phase-pin]').forEach((row) => {
            const [name, pin] = row.dataset.phasePin.split('.');
            const item = device.phase_view?.[name]?.[pin] || {};
            const cell = row.querySelector('[data-phase-state]');
            if (!item.configured) cell.innerHTML = '<span class="badge text-bg-light">Не откалибровано</span>';
            else if (stale || item.active === null || item.active === undefined) cell.innerHTML = '<span class="text-muted">Нет данных</span>';
            else if (item.active) cell.innerHTML = '<span class="badge text-bg-success">Есть</span>';
            else cell.innerHTML = '<span class="badge text-bg-danger">Нет</span>';
        });
    }

    function renderInputTest(card, device) {
        const live = card.querySelector('[data-input-test-live]');
        const captureForm = card.querySelector('[data-input-test-capture]');
        const resetForm = card.querySelector('[data-input-test-reset]');
        const confirmForm = card.querySelector('[data-input-test-confirm]');
        if (!live) return;
        const active = device.input_test?.active;
        const latest = device.input_test?.latest;
        const session = active || null;
        if (captureForm) captureForm.hidden = !session || session.phase !== 'armed';
        if (resetForm) resetForm.hidden = !session;
        const candidate = session?.candidate || (!session && latest?.candidate) || null;
        if (confirmForm) {
            confirmForm.hidden = !candidate;
            const label = confirmForm.querySelector('[data-input-test-candidate]');
            const level = confirmForm.querySelector('[name="active_level"]');
            if (label && candidate) label.textContent = `${candidate.connector}.${candidate.pin} -> ${candidate.source}.bit${candidate.bit}`;
            if (level && candidate && candidate.active_level !== null && candidate.active_level !== undefined) level.value = String(candidate.active_level);
        }
        if (session) {
            const stable = (session.stable || []).map((item) => `${item.label}: ${item.from} -> ${item.to}`).join('\n') || '—';
            const lines = (session.lines || []).map((item) => `${formatDate(item.at)} ${item.label} ${item.from} -> ${item.to}`).join('\n');
            const verdict = session.verdict === 'AMBIGUOUS'
                ? `RESULT:\nAMBIGUOUS\n${(session.stable || []).map((item) => item.label).join('\n')}`
                : session.verdict === 'NO CHANGE'
                    ? 'RESULT:\nNO CHANGE'
                    : session.verdict === 'RESULT' && candidate
                        ? `RESULT:\n${candidate.connector}.${candidate.pin} -> ${candidate.source}.bit${candidate.bit}\nactive_level candidate = ${candidate.active_level}`
                        : session.phase === 'after'
                            ? 'Ждём 3 STATE после переключения'
                            : session.baseline_ready
                                ? ''
                                : 'Ждём стабильный baseline';
            live.textContent = [
                session.baseline_ready ? `BASELINE\nU2=${session.baseline_u2}\nU3=${session.baseline_u3}` : 'BASELINE\nждём 3 одинаковых STATE',
                session.phase === 'done' ? `BEFORE:\nU2=${session.before_u2}\nU3=${session.before_u3}\nAFTER:\nU2=${session.after_u2}\nU3=${session.after_u3}\nSTABLE DIFF:\n${stable}` : '',
                verdict,
                'Отладочный журнал',
                lines || '—',
            ].filter((part) => part !== undefined).join('\n');
            return;
        }
        if (!latest) {
            live.textContent = '';
            return;
        }
        const transitions = Object.entries(latest.transitions || {}).map(([label, chain]) => `${label}: ${chain}`).join('\n');
        live.textContent = [
            'TEST RESULT',
            `Changed bits: ${(latest.changed_bits || []).join(', ') || 'none'}`,
            'Transitions:',
            transitions || '—',
            `${latest.connector} pin ${latest.pin}`,
            latest.duration_seconds != null ? `Duration: ${latest.duration_seconds}s` : '',
        ].filter(Boolean).join('\n');
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
        renderDiagnostics(card, device);
        renderInputTest(card, device);

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
        const pollMs = Math.max(250, Number(root.dataset.pollMs) || 500);

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
                if (!stopped) timer = window.setTimeout(refresh, pollMs);
            }
        }

        async function postTest(url, body) {
            const response = await fetch(url, {
                method: 'POST',
                body,
                headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
            });
            if (!response.ok) throw new Error('Не удалось выполнить тест входов.');
            await refresh();
        }

        root.querySelectorAll('[data-input-test]').forEach((block) => {
            block.querySelector('[data-input-test-start]')?.addEventListener('submit', async (event) => {
                event.preventDefault();
                await postTest(block.dataset.startUrl, new FormData(event.currentTarget));
            });
            block.querySelector('[data-input-test-capture]')?.addEventListener('submit', async (event) => {
                event.preventDefault();
                await postTest(block.dataset.captureUrl, new FormData(event.currentTarget));
            });
            block.querySelector('[data-input-test-reset]')?.addEventListener('submit', async (event) => {
                event.preventDefault();
                await postTest(block.dataset.resetUrl, new FormData(event.currentTarget));
            });
            block.querySelector('[data-input-test-confirm]')?.addEventListener('submit', async (event) => {
                event.preventDefault();
                await postTest(block.dataset.confirmUrl, new FormData(event.currentTarget));
            });
        });

        root.querySelectorAll('[data-phase-map-form]').forEach((form) => {
            form.addEventListener('submit', async (event) => {
                event.preventDefault();
                const card = form.closest('[data-device-card]');
                try {
                    const response = await fetch(form.action, {
                        method: 'POST',
                        body: new FormData(form),
                        headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
                    });
                    if (!response.ok) throw new Error('Не удалось сохранить сопоставление.');
                    await refresh();
                } catch (error) {
                    const status = card?.querySelector('[data-command-status]');
                    if (status) {
                        status.className = 'alert alert-danger py-2 mt-3 mb-3';
                        status.textContent = error.message || 'Не удалось сохранить сопоставление.';
                    }
                }
            });
        });

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
            changedUntil.clear();
        };
        window.addEventListener('opora:before-navigate', destroy, { once: true });
        refresh();
    }

    document.addEventListener('DOMContentLoaded', boot);
    window.addEventListener('opora:navigated', boot);
    window.OporaDevices = { init: boot };
})();
