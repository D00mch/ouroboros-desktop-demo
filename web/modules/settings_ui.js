function providerCard({ id, title, icon, hint, body, open = false }) {
    return `
        <details class="settings-provider-card" data-provider-card="${id}" ${open ? 'open' : ''}>
            <summary>
                <div class="settings-provider-title">
                    ${icon ? `<img src="${icon}" alt="" class="settings-provider-icon">` : ''}
                    <span>${title}</span>
                </div>
                <span class="settings-provider-hint">${hint || ''}</span>
            </summary>
            <div class="settings-provider-body">
                ${body}
            </div>
        </details>
    `;
}

function secretField({ id, settingKey, label, placeholder }) {
    return `
        <div class="form-field">
            <label>${label}</label>
            <div class="secret-input-row">
                <input id="${id}" data-secret-setting="${settingKey}" class="secret-input" type="password" placeholder="${placeholder}">
                <button type="button" class="settings-ghost-btn secret-toggle" data-target="${id}">Show</button>
                <button type="button" class="settings-ghost-btn secret-clear" data-target="${id}">Clear</button>
            </div>
        </div>
    `;
}

function modelCard({ title, copy, inputId, toggleId, defaultValue }) {
    return `
        <div class="settings-model-card">
            <div class="settings-model-header">
                <div>
                    <h4>${title}</h4>
                    <p>${copy}</p>
                </div>
                <label class="local-toggle"><input type="checkbox" id="${toggleId}"> Local</label>
            </div>
            <div class="model-picker" data-model-picker>
                <input
                    id="${inputId}"
                    value="${defaultValue}"
                    autocomplete="off"
                    spellcheck="false"
                >
                <div class="model-picker-results" hidden></div>
            </div>
        </div>
    `;
}

function effortField({ id, label, defaultValue }) {
    return `
        <div class="settings-effort-card">
            <label>${label}</label>
            <input id="${id}" type="hidden" value="${defaultValue}">
            <div class="settings-effort-group" data-effort-group data-effort-target="${id}">
                <button type="button" class="settings-effort-btn" data-effort-value="none">None</button>
                <button type="button" class="settings-effort-btn" data-effort-value="low">Low</button>
                <button type="button" class="settings-effort-btn" data-effort-value="medium">Medium</button>
                <button type="button" class="settings-effort-btn" data-effort-value="high">High</button>
            </div>
        </div>
    `;
}

export function renderSettingsPage() {
    return `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="12" cy="12" r="3"/></svg>
            <h2>Settings</h2>
        </div>
        <div class="settings-shell">
            <div class="settings-tabs-bar">
                <div class="settings-tabs">
                    <button class="settings-tab active" data-settings-tab="providers">Providers</button>
                    <button class="settings-tab" data-settings-tab="models">Models</button>
                    <button class="settings-tab" data-settings-tab="behavior">Behavior</button>
                    <button class="settings-tab" data-settings-tab="integrations">Integrations</button>
                    <button class="settings-tab" data-settings-tab="advanced">Advanced</button>
                </div>
            </div>

            <div class="settings-scroll">
                <section class="settings-panel active" data-settings-panel="providers">
                    <div class="settings-section-copy">
                        Demo runtime is fixed to the internal GigaChat endpoint. No API keys or provider setup are
                        collected by this build.
                    </div>
                    ${providerCard({
                        id: 'gigachat-demo',
                        title: 'GigaChat Demo',
                        icon: '',
                        hint: 'Hardcoded mTLS runtime',
                        open: true,
                        body: `
                            <div class="settings-inline-note">
                                Requests go to <code>https://gigachat-ift.sberdevices.delta.sbrf.ru/v1/chat/completions</code>
                                with model <code>glm-5.1</code>. The server must provide
                                <code>~/crt/giga.pem</code>, <code>~/crt/giga.key</code>, and <code>~/crt/cp.pem</code>.
                            </div>
                        `,
                    })}
                    <div hidden>
                        <input id="s-openrouter" value="">
                        <input id="s-openai" value="">
                        <input id="s-openai-base-url" value="">
                        <input id="s-openai-compatible-key" value="">
                        <input id="s-openai-compatible-base-url" value="">
                        <input id="s-cloudru-key" value="">
                        <input id="s-cloudru-base-url" value="">
                        <input id="s-anthropic" value="">
                        <div id="settings-claude-code-panel"></div>
                        <button type="button" id="btn-claude-code-install"></button>
                        <span id="settings-claude-code-status"></span>
                        <div id="settings-claude-code-copy"></div>
                    </div>
                    <div class="form-section compact">
                        <h3>Network Gate</h3>
                        <div class="form-row">${secretField({
                            id: 's-network-password',
                            settingKey: 'OUROBOROS_NETWORK_PASSWORD',
                            label: 'Network Password (optional)',
                            placeholder: 'Leave blank to keep the network surface open',
                        })}</div>
                        <div class="settings-inline-note">Adds a password wall only for non-localhost app and API access. Leave it blank if you use Ouroboros only on this machine or inside a trusted private network. External binds still start without it, but startup logs a warning.</div>
                        <div id="settings-lan-hint" class="settings-lan-hint" hidden></div>
                    </div>
                </section>

                <section class="settings-panel" data-settings-panel="models">
                    <div class="form-section">
                        <h3>Demo Model</h3>
                        <div class="settings-section-copy">
                            Model routing is disabled in this demo build. All task, code, light, fallback,
                            review, and scope-review lanes use <code>glm-5.1</code>.
                        </div>
                        <div class="panel-card">
                            <h3>Active runtime</h3>
                            <p><code>glm-5.1</code> via the fixed GigaChat mTLS endpoint.</p>
                            <span id="settings-model-catalog-status" class="settings-inline-status">Model catalog disabled for demo runtime.</span>
                            <button type="button" class="settings-ghost-btn" id="btn-refresh-model-catalog" hidden>Refresh Model Catalog</button>
                        </div>
                        <div hidden>
                            <input id="s-model" value="glm-5.1">
                            <input id="s-model-code" value="glm-5.1">
                            <input id="s-model-light" value="glm-5.1">
                            <input id="s-model-fallback" value="glm-5.1">
                            <input id="s-claude-code-model" value="">
                            <input id="s-review-models" value="glm-5.1,glm-5.1,glm-5.1">
                            <input id="s-scope-review-model" value="glm-5.1">
                            <input id="s-websearch-model" value="">
                            <input type="checkbox" id="s-local-main">
                            <input type="checkbox" id="s-local-code">
                            <input type="checkbox" id="s-local-light">
                            <input type="checkbox" id="s-local-fallback">
                        </div>
                    </div>
                </section>

                <section class="settings-panel" data-settings-panel="behavior">
                    <div class="form-section">
                        <h3>Reasoning Effort</h3>
                        <div class="settings-section-copy">Controls how deeply the model thinks per task type. Higher effort = slower but more thorough.</div>
                        <div class="settings-effort-grid">
                            ${effortField({ id: 's-effort-task', label: 'Task / Chat', defaultValue: 'medium' })}
                            ${effortField({ id: 's-effort-evolution', label: 'Evolution', defaultValue: 'high' })}
                            ${effortField({ id: 's-effort-review', label: 'Review', defaultValue: 'medium' })}
                            ${effortField({ id: 's-effort-scope-review', label: 'Scope Review', defaultValue: 'high' })}
                            ${effortField({ id: 's-effort-consciousness', label: 'Consciousness', defaultValue: 'low' })}
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>Review Enforcement</h3>
                        <div class="settings-section-copy"><code>Advisory</code> keeps review visible but non-blocking. <code>Blocking</code> stops commits when critical findings remain unresolved.</div>
                        <div class="settings-effort-card">
                            <label>Enforcement Mode</label>
                            <input id="s-review-enforcement" type="hidden" value="advisory">
                            <div class="settings-effort-group" data-effort-group data-enforcement-group data-effort-target="s-review-enforcement">
                                <button type="button" class="settings-effort-btn" data-effort-value="advisory">Advisory</button>
                                <button type="button" class="settings-effort-btn" data-effort-value="blocking">Blocking</button>
                            </div>
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>Runtime Mode</h3>
                        <div class="settings-section-copy">
                            Separate axis from Review Enforcement. Controls how far Ouroboros is allowed to self-modify.
                            <code>Light</code> blocks repo self-modification but allows reviewed + enabled skills to run.
                            <code>Advanced</code> is the default &mdash; self-modify the evolutionary layer; protected core/contract/release files stay guarded by the shared runtime-mode policy.
                            <code>Pro</code> can edit protected core/contract/release surfaces, but commits still go through the normal triad + scope review gate; Advanced remains limited to the evolutionary layer.
                            <br><strong>Owner controlled:</strong> desktop builds ask the launcher for native confirmation before saving a mode change.
                            Web/Docker sessions can view the current mode but cannot elevate it from this page.
                        </div>
                        <div class="settings-effort-card">
                            <label>Runtime Mode</label>
                            <input id="s-runtime-mode" type="hidden" value="advanced">
                            <div class="settings-effort-group" data-effort-group data-runtime-mode-group data-effort-target="s-runtime-mode" title="Runtime mode changes require native launcher confirmation and restart.">
                                <button type="button" class="settings-effort-btn" data-effort-value="light">Light</button>
                                <button type="button" class="settings-effort-btn" data-effort-value="advanced">Advanced</button>
                                <button type="button" class="settings-effort-btn" data-effort-value="pro">Pro</button>
                            </div>
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>External Skills Repo</h3>
                        <div class="settings-section-copy">
                            Optional EXTRA discovery path on top of the in-data-plane
                            <code>data/skills/{native,clawhub,external}/</code> tree.
                            Ouroboros scans this for additional skill packages without
                            cloning or pulling them. Leave empty to use only the data plane.
                        </div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Skills Repo Path</label>
                                <input id="s-skills-repo-path" placeholder="~/Ouroboros/skills or /absolute/path/to/skills">
                                <div class="settings-inline-note">Absolute or <code>~</code>-prefixed path. Ouroboros never clones/pulls this directory — you manage it yourself.</div>
                            </div>
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>ClawHub Marketplace</h3>
                        <div class="settings-section-copy">
                            Always-on surface for installing community skills from
                            <a href="https://clawhub.ai" target="_blank" rel="noopener">clawhub.ai</a>.
                            The Skills page exposes a Marketplace tab; every install is
                            staged, OpenClaw frontmatter is translated into the
                            Ouroboros manifest shape, and the standard tri-model review runs
                            automatically before the skill becomes executable. Plugins (Node)
                            are filtered out — only skill packages are installable.
                        </div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Registry URL</label>
                                <input id="s-clawhub-registry-url" placeholder="https://clawhub.ai/api/v1">
                                <div class="settings-inline-note">Override only for self-hosted mirrors. Hostname must be <code>clawhub.ai</code> or localhost.</div>
                            </div>
                        </div>
                    </div>
                </section>

                <section class="settings-panel" data-settings-panel="integrations">
                    <div class="form-section">
                        <h3>Telegram Bridge</h3>
                        <div class="form-row">${secretField({
                            id: 's-telegram-token',
                            settingKey: 'TELEGRAM_BOT_TOKEN',
                            label: 'Bot Token',
                            placeholder: '123456:ABCDEF...',
                        })}</div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Primary Chat ID (optional)</label>
                                <input id="s-telegram-chat-id" placeholder="123456789">
                            </div>
                        </div>
                        <div class="settings-inline-note">If no primary chat is pinned, the bridge binds to the first active Telegram chat and keeps replies attached there.</div>
                    </div>

                    <div class="form-section">
                        <h3>SberChat</h3>
                        <div class="settings-section-copy">SberChat SDK bridge for one pinned group. Changes require restart.</div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Endpoint</label>
                                <input id="s-dialogs-endpoint" placeholder="epbotsift.sberchat.sberbank.ru:443">
                            </div>
                            ${secretField({
                                id: 's-dialogs-bot-token',
                                settingKey: 'DIALOGS_BOT_TOKEN',
                                label: 'Bot Token',
                                placeholder: 'Dialogs bot token',
                            })}
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label>Group ID</label>
                                <input id="s-dialogs-group-id" type="number" value="2112986678">
                            </div>
                            <div class="form-field">
                                <label>Root Certificates</label>
                                <input id="s-dialogs-root-certificates" placeholder="~/ru_certs/russian_trusted_bundle.pem">
                            </div>
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label>App ID</label>
                                <input id="s-dialogs-app-id" type="number" value="0">
                            </div>
                            <div class="form-field">
                                <label>Trust Server Certificate</label>
                                <label class="local-toggle"><input type="checkbox" id="s-dialogs-trust-certs"> Pin fetched certificate</label>
                            </div>
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label>App Title</label>
                                <input id="s-dialogs-app-title" placeholder="Ouroboros">
                            </div>
                            <div class="form-field">
                                <label>Device Title</label>
                                <input id="s-dialogs-device-title" placeholder="Ouroboros">
                            </div>
                        </div>
                        <div class="form-grid three">
                            <div class="form-field">
                                <label>Keepalive Time (ms)</label>
                                <input id="s-dialogs-keepalive-time" type="number" value="30000">
                            </div>
                            <div class="form-field">
                                <label>Keepalive Timeout (ms)</label>
                                <input id="s-dialogs-keepalive-timeout" type="number" value="10000">
                            </div>
                            <div class="form-field">
                                <label>Keepalive Without Calls</label>
                                <label class="local-toggle"><input type="checkbox" id="s-dialogs-keepalive-permit"> Enable</label>
                            </div>
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>GitHub</h3>
                        <div class="form-row">${secretField({
                            id: 's-gh-token',
                            settingKey: 'GITHUB_TOKEN',
                            label: 'GitHub Token',
                            placeholder: 'ghp_...',
                        })}</div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>GitHub Repo</label>
                                <input id="s-gh-repo" placeholder="owner/repo-name">
                            </div>
                        </div>
                        <div class="settings-inline-note">Only needed for in-app remote sync features. Safe to leave empty if you work locally.</div>
                    </div>
                    <div class="form-section">
                        <h3>A2A Protocol</h3>
                        <div class="settings-section-copy">Agent-to-Agent communication server. Disabled by default. Requires restart to toggle.</div>
                        <div class="form-row">
                            <div class="form-field checkbox-field">
                                <label for="s-a2a-enabled">Enable A2A Server</label>
                                <input type="checkbox" id="s-a2a-enabled">
                            </div>
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label for="s-a2a-host">A2A Host</label>
                                <input type="text" id="s-a2a-host" placeholder="127.0.0.1">
                            </div>
                            <div class="form-field">
                                <label for="s-a2a-port">A2A Port</label>
                                <input type="number" id="s-a2a-port" placeholder="18800">
                            </div>
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label for="s-a2a-agent-name">Agent Name (override)</label>
                                <input type="text" id="s-a2a-agent-name" placeholder="Auto-detected from identity.md">
                            </div>
                            <div class="form-field">
                                <label for="s-a2a-agent-description">Agent Description (override)</label>
                                <input type="text" id="s-a2a-agent-description" placeholder="Auto-detected from identity.md">
                            </div>
                        </div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label for="s-a2a-max-concurrent">Max Concurrent Tasks</label>
                                <input type="number" id="s-a2a-max-concurrent" placeholder="3">
                            </div>
                            <div class="form-field">
                                <label for="s-a2a-ttl-hours">Task TTL (hours)</label>
                                <input type="number" id="s-a2a-ttl-hours" placeholder="24">
                            </div>
                        </div>
                    </div>
                </section>

                <section class="settings-panel" data-settings-panel="advanced">
                    <div hidden>
                        <input id="s-local-source" value="">
                        <input id="s-local-filename" value="">
                        <input id="s-local-port" type="number" value="8766">
                        <input id="s-local-gpu-layers" type="number" value="0">
                        <input id="s-local-ctx" type="number" value="16384">
                        <input id="s-local-chat-format" value="">
                        <button type="button" id="btn-local-start"></button>
                        <button type="button" id="btn-local-stop"></button>
                        <button type="button" id="btn-local-test"></button>
                        <button type="button" id="btn-local-install-runtime"></button>
                        <div id="local-model-status"></div>
                        <div id="local-model-progress-wrap"><div id="local-model-progress-bar"></div></div>
                        <div id="local-model-test-result"></div>
                    </div>

                    <div class="form-section">
                        <h3>Runtime Limits</h3>
                        <div class="settings-section-copy">Workers control parallel task capacity. Timeout values are safety rails for long or stuck tasks and tools.</div>
                        <div class="form-grid two">
                            <div class="form-field">
                                <label>Max Workers</label>
                                <input id="s-workers" type="number" min="1" max="10" value="5">
                            </div>
                            <div class="form-field">
                                <label>Soft Timeout (s)</label>
                                <input id="s-soft-timeout" type="number" value="600">
                            </div>
                            <div class="form-field">
                                <label>Hard Timeout (s)</label>
                                <input id="s-hard-timeout" type="number" value="1800">
                            </div>
                            <div class="form-field">
                                <label>Tool Timeout (s)</label>
                                <input id="s-tool-timeout" type="number" value="120">
                            </div>
                        </div>
                    </div>

                    <div class="form-section danger">
                        <h3>Danger Zone</h3>
                        <div class="settings-inline-note">Reset still uses the current restart-based flow. This clears runtime data but keeps the repo.</div>
                        <button class="btn btn-danger" id="btn-reset">Reset All Data</button>
                    </div>
                </section>
            </div>

            <div class="settings-footer">
                <button type="button" class="btn btn-secondary" id="btn-reload-settings">Reload Settings</button>
                <button class="btn btn-save" id="btn-save-settings">Save Settings</button>
                <span id="settings-unsaved-indicator" class="settings-inline-status settings-unsaved-indicator" hidden>Unsaved changes.</span>
                <div id="settings-status" class="settings-inline-status"></div>
            </div>
        </div>
    `;
}

export function bindSettingsTabs(root) {
    const tabs = Array.from(root.querySelectorAll('.settings-tab'));
    const panels = Array.from(root.querySelectorAll('.settings-panel'));
    const scrollRoot = root.querySelector('.settings-scroll');

    function activate(tabName) {
        tabs.forEach((button) => {
            button.classList.toggle('active', button.dataset.settingsTab === tabName);
        });
        panels.forEach((panel) => {
            panel.classList.toggle('active', panel.dataset.settingsPanel === tabName);
        });
        if (scrollRoot) scrollRoot.scrollTop = 0;
    }

    tabs.forEach((button) => {
        button.addEventListener('click', () => activate(button.dataset.settingsTab));
    });
}

export function bindSecretInputs(root) {
    root.querySelectorAll('.secret-input').forEach((input) => {
        input.addEventListener('focus', () => {
            if (input.value.includes('...')) input.value = '';
        });
        input.addEventListener('input', () => {
            if (input.value.trim()) delete input.dataset.forceClear;
        });
    });

    root.querySelectorAll('.secret-toggle').forEach((button) => {
        button.addEventListener('click', () => {
            const target = root.querySelector(`#${button.dataset.target}`);
            if (!target) return;
            const nextType = target.type === 'password' ? 'text' : 'password';
            target.type = nextType;
            button.textContent = nextType === 'password' ? 'Show' : 'Hide';
        });
    });

    root.querySelectorAll('.secret-clear').forEach((button) => {
        button.addEventListener('click', () => {
            const target = root.querySelector(`#${button.dataset.target}`);
            if (!target) return;
            target.value = '';
            target.type = 'password';
            target.dataset.forceClear = '1';
            const toggle = root.querySelector(`.secret-toggle[data-target="${button.dataset.target}"]`);
            if (toggle) toggle.textContent = 'Show';
        });
    });
}
