document.addEventListener("DOMContentLoaded", () => {
    const platformName = "BayAfya";
    const toastContainer = document.getElementById("toastContainer");
    const pwaBanner = document.getElementById("pwaInstallBanner");
    const pwaInstallTrigger = document.querySelector("[data-pwa-install-trigger]");
    const pwaDismissTrigger = document.querySelector("[data-pwa-dismiss]");
    const assistantPanel = document.getElementById("bayhealthAssistantPanel");
    const assistantPrompt = document.getElementById("assistantPrompt");
    const assistantAskButton = document.getElementById("assistantAskButton");
    const assistantClearButton = document.getElementById("assistantClearButton");
    const assistantSummary = document.getElementById("assistantSummary");
    const assistantSuggestions = document.getElementById("assistantSuggestions");
    const assistantSafety = document.getElementById("assistantSafety");
    const assistantSummaryBadge = document.getElementById("assistantSummaryBadge");
    const assistantSuggestionsBadge = document.getElementById("assistantSuggestionsBadge");
    const assistantSafetyBadge = document.getElementById("assistantSafetyBadge");
    const assistantChatStream = document.getElementById("assistantChatStream");
    const assistantPromptChips = document.getElementById("assistantPromptChips");
    const assistantModeBar = document.getElementById("assistantModeBar");
    const assistantWorkspaceRail = document.getElementById("assistantWorkspaceRail");
    const assistantWorkspaceDots = document.getElementById("assistantWorkspaceDots");
    const assistantFab = document.getElementById("bayhealthAssistantFab");
    let deferredInstallPrompt = null;
    let assistantScrollIdleTimer = null;
    let lastScrollPosition = window.scrollY || 0;
    let assistantMode = "";
    let refreshLiveDashboardState = null;
    let refreshCurrentPageLiveRoot = null;
    let hospitalLiveSocket = null;
    let hospitalLiveRefreshTimer = null;

    function clearElement(node) {
        if (!node) return;
        while (node.firstChild) {
            node.removeChild(node.firstChild);
        }
    }

    function appendToast(title, message, variant = "primary") {
        if (!toastContainer || !window.bootstrap) return;

        const toneClass = {
            primary: "text-bg-primary",
            success: "text-bg-success",
            warning: "text-bg-warning",
            danger: "text-bg-danger",
            info: "text-bg-info"
        }[variant] || "text-bg-primary";

        const toneIcon = {
            primary: "bi-info-circle-fill",
            success: "bi-check-circle-fill",
            warning: "bi-exclamation-triangle-fill",
            danger: "bi-x-octagon-fill",
            info: "bi-chat-square-heart-fill"
        }[variant] || "bi-info-circle-fill";

        const toast = document.createElement("div");
        toast.className = `toast align-items-center border-0 ${toneClass}`;
        toast.setAttribute("role", "alert");
        toast.setAttribute("aria-live", "assertive");
        toast.setAttribute("aria-atomic", "true");
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <div class="toast-title-row">
                        <span class="toast-brand-icon"><i class="bi bi-heart-pulse-fill"></i></span>
                        <span class="fw-semibold">${title || platformName}</span>
                    </div>
                    <div class="toast-message-row">
                        <span class="toast-variant-icon"><i class="bi ${toneIcon}"></i></span>
                        <span>${message}</span>
                    </div>
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;

        toastContainer.appendChild(toast);
        const instance = new bootstrap.Toast(toast, { delay: 4500 });
        instance.show();
        toast.addEventListener("hidden.bs.toast", () => toast.remove());
    }

    function isStandaloneDisplay() {
        return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
    }

    function hidePwaBanner() {
        if (pwaBanner) {
            pwaBanner.classList.add("d-none");
        }
    }

    function showPwaBanner() {
        if (!pwaBanner || isStandaloneDisplay()) {
            return;
        }
        const dismissed = sessionStorage.getItem("baycare-pwa-dismissed") === "1";
        if (!dismissed && deferredInstallPrompt) {
            pwaBanner.classList.remove("d-none");
        }
    }

    function withBusyButton(button, busyLabel, callback) {
        if (!button) {
            callback();
            return;
        }
        const original = button.innerHTML;
        button.disabled = true;
        button.innerHTML = busyLabel
            ? `<span class="spinner-border spinner-border-sm me-2"></span>${busyLabel}`
            : `<span class="spinner-border spinner-border-sm"></span>`;
        Promise.resolve(callback()).finally(() => {
            button.disabled = false;
            button.innerHTML = original;
        });
    }

    const escapeSelector = (value) => (window.CSS && typeof window.CSS.escape === "function" ? window.CSS.escape(value) : String(value).replace(/"/g, '\\"'));

    function clearInlineFormErrors(form) {
        if (!form) return;
        form.querySelectorAll("[data-inline-form-error]").forEach((node) => node.remove());
        form.querySelectorAll("[data-inline-form-error-summary]").forEach((node) => node.remove());
    }

    function getFormActionUrl(form, fallback = window.location.href) {
        if (!(form instanceof HTMLFormElement)) return fallback;
        const action = form.getAttribute("action");
        return action && action.trim() ? action : fallback;
    }

    function getCsrfToken(source = document) {
        if (source instanceof HTMLFormElement) {
            const localToken = source.querySelector("[name=csrfmiddlewaretoken]")?.value;
            if (localToken) return localToken;
        }
        if (source instanceof HTMLElement) {
            const scopedToken = source.querySelector?.("[name=csrfmiddlewaretoken]")?.value;
            if (scopedToken) return scopedToken;
        }
        return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    }

    function showInlineFormErrors(form, errors) {
        if (!form || !errors) return;
        const summaryErrors = [];
        Object.entries(errors).forEach(([name, messages]) => {
            if (name === "__all__" || name === "non_field_errors") {
                summaryErrors.push(...(Array.isArray(messages) ? messages : [String(messages || "")]));
                return;
            }
            const field = form.querySelector(`[name="${escapeSelector(name)}"]`);
            if (!field) return;
            const stack = field.closest(".form-field-stack") || field.closest(".form-check") || field.parentElement;
            if (!stack) return;
            const errorNode = document.createElement("div");
            errorNode.className = "bh-field-error";
            errorNode.setAttribute("data-inline-form-error", name);
            errorNode.textContent = Array.isArray(messages) ? messages.join(" ") : String(messages || "");
            stack.appendChild(errorNode);
        });
        if (summaryErrors.length) {
            const summaryNode = document.createElement("div");
            summaryNode.className = "bh-form-error";
            summaryNode.setAttribute("data-inline-form-error-summary", "1");
            summaryNode.textContent = summaryErrors.join(" ");
            const anchor = form.querySelector(".form-field-stack") || form.querySelector(".row") || form.firstElementChild || form;
            anchor.parentNode?.insertBefore(summaryNode, anchor);
        }
    }

    function parseRefreshSelectors(value = "") {
        return String(value || "")
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function debounce(callback, delay = 300) {
        let timer = null;
        return (...args) => {
            window.clearTimeout(timer);
            timer = window.setTimeout(() => callback(...args), delay);
        };
    }

    function scorePasswordStrength(value) {
        let score = 0;
        if (!value) return score;
        if (value.length >= 8) score += 1;
        if (value.length >= 12) score += 1;
        if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1;
        if (/\d/.test(value)) score += 1;
        if (/[^A-Za-z0-9]/.test(value)) score += 1;
        if (value.length >= 16 && /[^A-Za-z0-9]/.test(value)) score += 1;
        return Math.min(score, 5);
    }

    function passwordStrengthTier(score) {
        if (score <= 1) return { label: "Weak", tone: "danger", width: "20%" };
        if (score === 2) return { label: "Fair", tone: "warning", width: "40%" };
        if (score === 3) return { label: "Strong", tone: "info", width: "65%" };
        if (score === 4) return { label: "Very strong", tone: "success", width: "82%" };
        return { label: "Extra strong", tone: "success", width: "100%" };
    }

    function bindStandalonePasswordMeters() {
        document.querySelectorAll("[data-password-change-form], [data-password-reset-form]").forEach((form) => {
            if (form.dataset.passwordMeterBound === "1") return;
            const passwordField = form.querySelector("[data-password-strength-input]");
            const confirmField = form.querySelector("[data-password-confirm-input]");
            const meter = form.querySelector("[data-password-meter]");
            const meterLabel = form.querySelector("[data-password-meter-label]");
            const matchLabel = form.querySelector("[data-password-match-label]");
            if (!passwordField) return;
            const sync = () => {
                const score = scorePasswordStrength(passwordField.value || "");
                const tier = passwordStrengthTier(score);
                if (meter) {
                    meter.style.width = tier.width;
                    meter.dataset.tone = tier.tone;
                }
                if (meterLabel) {
                    meterLabel.textContent = passwordField.value ? `Password strength: ${tier.label}` : "Password strength: waiting";
                }
                if (confirmField && matchLabel) {
                    if (!confirmField.value && !passwordField.value) {
                        matchLabel.textContent = "Confirm password to continue.";
                        matchLabel.className = "bh-field-help";
                    } else if (confirmField.value === passwordField.value) {
                        matchLabel.textContent = "Passwords match.";
                        matchLabel.className = "bh-field-help text-success";
                    } else {
                        matchLabel.textContent = "Passwords do not match.";
                        matchLabel.className = "bh-field-error d-inline-flex";
                    }
                }
            };
            passwordField.addEventListener("input", sync);
            passwordField.addEventListener("blur", sync);
            if (confirmField) {
                confirmField.addEventListener("input", sync);
                confirmField.addEventListener("blur", sync);
            }
            sync();
            form.dataset.passwordMeterBound = "1";
        });
    }

    function initPasswordVisibilityToggles(root = document) {
        root.querySelectorAll('input[type="password"]').forEach((input) => {
            if (input.dataset.passwordToggleBound === "1") return;
            if (input.type === "hidden") return;

            const shell = document.createElement("div");
            shell.className = "password-visibility-shell";
            input.parentNode.insertBefore(shell, input);
            shell.appendChild(input);

            const button = document.createElement("button");
            button.type = "button";
            button.className = "password-visibility-toggle";
            button.setAttribute("aria-label", "Show password");
            button.innerHTML = '<i class="bi bi-eye"></i>';
            shell.appendChild(button);

            const sync = () => {
                const visible = input.type === "text";
                button.innerHTML = visible ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
                button.setAttribute("aria-label", visible ? "Hide password" : "Show password");
                button.setAttribute("aria-pressed", visible ? "true" : "false");
            };

            button.addEventListener("click", () => {
                input.type = input.type === "password" ? "text" : "password";
                sync();
                input.focus({ preventScroll: true });
                try {
                    const length = input.value.length;
                    input.setSelectionRange(length, length);
                } catch (_) {
                    return;
                }
            });

            sync();
            input.dataset.passwordToggleBound = "1";
        });
    }

    function bindAuthActionButtons() {
        document.querySelectorAll("[data-auth-submit]").forEach((button) => {
            if (button.dataset.authBound === "1") return;
            const form = button.closest("form");
            if (!form || form.matches("[data-password-change-form], [data-async-dashboard-form], [data-async-cart-form], [data-communications-async-form]")) return;
            button.dataset.authBound = "1";
            form.addEventListener("submit", () => {
                if (button.dataset.authBusy === "1") return;
                button.dataset.authBusy = "1";
                button.disabled = true;
                button.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>`;
            });
        });

        document.querySelectorAll("[data-auth-link]").forEach((link) => {
            if (link.dataset.authLinkBound === "1") return;
            link.dataset.authLinkBound = "1";
            link.addEventListener("click", (event) => {
                if (link.dataset.authBusy === "1") return;
                const href = link.getAttribute("href");
                if (!href || href.startsWith("#")) return;
                event.preventDefault();
                link.dataset.authBusy = "1";
                const original = link.innerHTML;
                link.setAttribute("aria-busy", "true");
                link.classList.add("is-loading");
                link.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>`;
                window.setTimeout(() => {
                    window.location.href = href;
                }, 120);
                window.setTimeout(() => {
                    link.innerHTML = original;
                    link.classList.remove("is-loading");
                    link.removeAttribute("aria-busy");
                    link.dataset.authBusy = "0";
                }, 8000);
            });
        });
    }

    function initEmailVerificationFlow() {
        document.querySelectorAll("[data-email-verification-form]").forEach((form) => {
            if (form.dataset.emailVerificationBound === "1") return;
            form.dataset.emailVerificationBound = "1";

            const shell = form.closest("[data-email-verification-shell]");
            const digitInputs = Array.from(form.querySelectorAll("[data-verification-digit]"));
            const hiddenCodeInput = form.querySelector("[data-email-verification-code]");
            const feedback = shell?.querySelector("[data-email-verification-feedback]");
            const emailInput = form.querySelector("[name='email']");
            let submitting = false;

            if (!digitInputs.length || !hiddenCodeInput || !emailInput) return;

            const setFeedback = (message, tone = "") => {
                if (!feedback) return;
                feedback.textContent = message || "";
                feedback.classList.remove("is-error", "is-success");
                if (tone) {
                    feedback.classList.add(`is-${tone}`);
                }
            };

            const setLocked = (locked) => {
                shell?.classList.toggle("is-locked", locked);
                digitInputs.forEach((input) => {
                    input.disabled = locked;
                });
            };

            const syncCode = () => {
                hiddenCodeInput.value = digitInputs.map((input) => (input.value || "").replace(/\D/g, "").slice(0, 1)).join("");
                return hiddenCodeInput.value;
            };

            const fillDigits = (digits) => {
                digitInputs.forEach((input, index) => {
                    input.value = digits[index] || "";
                });
                syncCode();
            };

            const renderVerifiedState = (message) => {
                if (!shell) return;
                shell.innerHTML = `
                    <div class="soft-section p-4">
                        <div class="fw-semibold mb-2">Email verified</div>
                        <div class="text-secondary small mb-3">${escapeHtml(message || "Your email address has been verified. You can now sign in.")}</div>
                        <div class="auth-inline-actions">
                            <a class="bh-btn bh-btn-primary" href="/login/" data-auth-link><i class="bi bi-box-arrow-in-right"></i><span>Sign in</span></a>
                        </div>
                    </div>
                `;
                bindAuthActionButtons();
            };

            const submitCode = async () => {
                const code = syncCode();
                if (submitting || code.length !== digitInputs.length) return;
                submitting = true;
                setFeedback("Verifying code now...", "");
                try {
                    const response = await fetch(getFormActionUrl(form), {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]")?.value || ""
                        },
                        body: new FormData(form)
                    });
                    const payload = await response.json().catch(() => ({}));
                    if (!response.ok || payload.ok === false) {
                        const message = payload.message || "The verification code could not be confirmed.";
                        setFeedback(message, "error");
                        appendToast("Verification error", message, "danger");
                        if (payload.locked_until) {
                            setLocked(true);
                        } else {
                            fillDigits("");
                            digitInputs[0]?.focus();
                        }
                        return;
                    }
                    setFeedback(payload.message || "Your email address has been verified.", "success");
                    appendToast("Email verified", payload.message || "Your email address has been verified.", "success");
                    renderVerifiedState(payload.message);
                } catch (_) {
                    const message = "Verification is temporarily unavailable. Please try again in a moment.";
                    setFeedback(message, "error");
                    appendToast("Verification error", message, "danger");
                } finally {
                    submitting = false;
                }
            };

            digitInputs.forEach((input, index) => {
                input.addEventListener("input", () => {
                    input.value = (input.value || "").replace(/\D/g, "").slice(0, 1);
                    const code = syncCode();
                    if (input.value && index < digitInputs.length - 1) {
                        digitInputs[index + 1].focus();
                        digitInputs[index + 1].select();
                    }
                    if (code.length === digitInputs.length) {
                        submitCode();
                    }
                });

                input.addEventListener("keydown", (event) => {
                    if (event.key === "Backspace" && !input.value && index > 0) {
                        digitInputs[index - 1].focus();
                        digitInputs[index - 1].value = "";
                        syncCode();
                    }
                    if (event.key === "ArrowLeft" && index > 0) {
                        event.preventDefault();
                        digitInputs[index - 1].focus();
                    }
                    if (event.key === "ArrowRight" && index < digitInputs.length - 1) {
                        event.preventDefault();
                        digitInputs[index + 1].focus();
                    }
                });

                input.addEventListener("paste", (event) => {
                    const pasted = (event.clipboardData?.getData("text") || "").replace(/\D/g, "").slice(0, digitInputs.length);
                    if (!pasted) return;
                    event.preventDefault();
                    fillDigits(pasted);
                    const code = syncCode();
                    const target = digitInputs[Math.min(code.length, digitInputs.length - 1)];
                    target?.focus();
                    if (code.length === digitInputs.length) {
                        submitCode();
                    }
                });
            });

            if (feedback?.textContent?.includes("locked until")) {
                setLocked(true);
            }
        });
    }

    function applyLiveMetrics(metrics) {
        if (!metrics) return;
        Object.entries(metrics).forEach(([key, value]) => {
            document.querySelectorAll(`[data-live-metric="${key}"]`).forEach((node) => {
                node.textContent = value;
            });
        });
    }

    function renderBayafyaWatchItem(item, isActive = false) {
        const toneClass = item.tone === "danger" ? "danger" : item.tone === "warning" ? "warning" : "";
        return `
            <div class="bayafya-watch-item bayafya-watch-tone-${escapeHtml(item.tone || "primary")}${isActive ? " is-active" : ""}" data-bayafya-watch-item data-watch-id="${escapeHtml(item.id || "")}"${isActive ? ' data-watch-active="true"' : ""}>
                <div class="d-flex justify-content-between align-items-start gap-3 mb-2">
                    <div class="fw-semibold">${escapeHtml(item.title || "BayAfya watch")}</div>
                    <div class="d-flex align-items-center gap-2">
                        <span class="status-pill ${toneClass}">${escapeHtml((item.tone || "primary").replace("_", " ").replace(/^./, (m) => m.toUpperCase()))}</span>
                        <button class="bayafya-watch-dismiss" type="button" data-watch-dismiss="${escapeHtml(item.id || "")}" aria-label="Dismiss signal"><i class="bi bi-x-lg"></i></button>
                    </div>
                </div>
                <div class="text-secondary small">${escapeHtml(item.detail || "")}</div>
                ${item.meta ? `<div class="text-secondary small mt-2">${escapeHtml(item.meta)}</div>` : ""}
            </div>
        `;
    }

    function renderBayafyaWatchEmptyState() {
        return `
            <div class="bayafya-watch-empty empty-state p-4 text-center" data-bayafya-watch-empty>
                <div class="empty-illustration mx-auto mb-3"><i class="bi bi-stars fs-2"></i></div>
                <div class="fw-semibold">No BayAfya watch signals right now</div>
                <div class="text-secondary small">Fresh clinical, operational, and care signals will appear here when something needs attention in the last 12 hours.</div>
            </div>
        `;
    }

    function applyBayafyaWatchItems(items) {
        document.querySelectorAll(".bayafya-watch").forEach((card) => {
            const list = card.querySelector("[data-bayafya-watch-list]");
            const countNode = card.querySelector("[data-bayafya-watch-count]");
            const toggle = card.querySelector("[data-bayafya-watch-toggle]");
            if (!list || !countNode) return;
            if (!items || !items.length) {
                clearElement(list);
                list.insertAdjacentHTML("beforeend", renderBayafyaWatchEmptyState());
                card.classList.remove("is-expanded");
                if (toggle) {
                    toggle.classList.add("d-none");
                    toggle.textContent = "Show more";
                    toggle.setAttribute("aria-expanded", "false");
                }
                countNode.innerHTML = `<i class="bi bi-broadcast"></i>0 signals`;
                return;
            }
            clearElement(list);
            items.forEach((item, index) => {
                list.insertAdjacentHTML("beforeend", renderBayafyaWatchItem(item, index === 0));
            });
            countNode.innerHTML = `<i class="bi bi-broadcast"></i>${items.length} signals`;
            if (toggle) {
                const showToggle = items.length > 1;
                toggle.classList.toggle("d-none", !showToggle);
                if (!showToggle) {
                    card.classList.remove("is-expanded");
                    toggle.textContent = "Show more";
                    toggle.setAttribute("aria-expanded", "false");
                }
            }
            initBayafyaWatch();
        });
    }

    function applySmartFillRows() {
        document.querySelectorAll("[data-smart-fill-row]").forEach((row) => {
            const columns = Array.from(row.querySelectorAll("[data-smart-fill-col]"));
            const visibleColumns = columns.filter((column) => !column.hidden && column.childElementCount > 0);
            columns.forEach((column) => column.classList.remove("smart-fill-expanded"));
            if (visibleColumns.length === 1) {
                visibleColumns[0].classList.add("smart-fill-expanded");
            }
        });
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function renderDoctorTaskCard(task) {
        const priorityClass = task.priority_slug === "critical" ? "danger" : task.priority_slug === "high" ? "warning" : "";
        return `
            <div class="soft-section p-3" data-doctor-task-card="${task.id}">
                <div class="d-flex justify-content-between align-items-start gap-3 mb-2">
                    <div>
                        <div class="fw-semibold">${escapeHtml(task.title)}</div>
                        <div class="text-secondary small">${escapeHtml(task.patient)}${task.hospital ? ` · ${escapeHtml(task.hospital)}` : ""}</div>
                    </div>
                    <span class="status-pill ${priorityClass}">${escapeHtml(task.priority)}</span>
                </div>
                <div class="text-secondary small mb-3">${escapeHtml(task.details)}</div>
                <div class="d-flex flex-wrap gap-2" data-doctor-task-actions="${task.id}">
                    <form method="post" action="/hospital/doctor/tasks/${task.id}/status/done/" data-async-dashboard-form data-async-behavior="doctor-task-status">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(getCsrfToken())}">
                        <button class="bh-btn bh-btn-inline bh-btn-primary" type="submit">Mark done</button>
                    </form>
                    <form method="post" action="/hospital/doctor/tasks/${task.id}/status/in_progress/" data-async-dashboard-form data-async-behavior="doctor-task-status">
                        <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(getCsrfToken())}">
                        <button class="bh-btn bh-btn-inline bh-btn-outline" type="submit">In progress</button>
                    </form>
                </div>
            </div>
        `;
    }

    function renderCarePlanCard(item) {
        return `
            <div class="soft-section p-3">
                <div class="fw-semibold">${escapeHtml(item.title)}</div>
                <div class="text-secondary small mb-2">${escapeHtml(item.patient)}${item.timeline ? ` · ${escapeHtml(item.timeline)}` : ""}</div>
                <div class="text-secondary small">${escapeHtml(item.goals)}</div>
            </div>
        `;
    }

    function renderReferralCard(item, inbound = false) {
        const priorityClass = item.priority_slug === "stat" ? "danger" : item.priority_slug === "urgent" ? "warning" : "";
        if (inbound) {
            return `
                <div class="soft-section p-3" data-referral-card="${item.id}">
                    <div class="fw-semibold">${escapeHtml(item.patient)}</div>
                    <div class="text-secondary small mb-2">From ${escapeHtml(item.referring_doctor || "Network clinician")}${item.source_hospital ? ` · ${escapeHtml(item.source_hospital)}` : ""}</div>
                    <div class="text-secondary small mb-3">${escapeHtml(item.reason)}</div>
                    <div class="d-flex flex-wrap gap-2" data-referral-actions="${item.id}">
                        <form method="post" action="/hospital/doctor/referrals/${item.id}/status/accepted/" data-async-dashboard-form data-async-behavior="referral-status">
                            <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(getCsrfToken())}">
                            <button class="bh-btn bh-btn-inline bh-btn-outline" type="submit">Accept</button>
                        </form>
                        <form method="post" action="/hospital/doctor/referrals/${item.id}/status/responded/" data-async-dashboard-form data-async-behavior="referral-status">
                            <input type="hidden" name="csrfmiddlewaretoken" value="${escapeHtml(getCsrfToken())}">
                            <button class="bh-btn bh-btn-inline bh-btn-primary" type="submit">Mark responded</button>
                        </form>
                    </div>
                </div>
            `;
        }
        return `
            <div class="soft-section p-3" data-referral-card="${item.id}">
                <div class="fw-semibold">${escapeHtml(item.patient)}</div>
                <div class="text-secondary small mb-2">To ${escapeHtml(item.target_doctor)}${item.target_hospital ? ` · ${escapeHtml(item.target_hospital)}` : ""}</div>
                <div class="text-secondary small mb-3">${escapeHtml(item.reason)}</div>
                <div class="d-flex flex-wrap gap-2">
                    <span class="status-pill ${priorityClass}">${escapeHtml(item.priority)}</span>
                    <span class="status-pill" data-referral-status="${item.id}">${escapeHtml(item.status)}</span>
                </div>
            </div>
        `;
    }

    function syncOpenChartButtons(activePatientId) {
        if (!activePatientId) return;
        document.querySelectorAll("[data-chart-button]").forEach((button) => {
            const isActive = String(button.dataset.patientId || "") === String(activePatientId);
            button.classList.toggle("bh-btn-primary", isActive);
            button.classList.toggle("bh-btn-outline", !isActive);
            button.innerHTML = isActive
                ? `<i class="bi bi-check2-circle"></i><span>Chart opened</span>`
                : `Open chart`;
        });
    }

    const initialActiveChartButton = document.querySelector("[data-chart-button].bh-btn-primary[data-patient-id]");
    if (initialActiveChartButton) {
        syncOpenChartButtons(initialActiveChartButton.dataset.patientId);
    }

    function rehydrateLivePageFeatures() {
        initPasswordVisibilityToggles();
        document.querySelectorAll("select[data-autocomplete]").forEach(enhanceAutocompleteSelect);
        document.querySelectorAll("input[data-entity-search]").forEach(enhanceEntitySearchInput);
        applySmartFillRows();
        initMetricSpotlights();
        initRotatingCardStacks();
        initCopyCodeButtons();
        initBayafyaWatch();
        initAdmissionActionWorkspace();
        initAdmissionDependentSelectors();
        initShiftAssignmentStaffPicker();
        initSidenavLinks();
        initMobileBottomNav();
        syncDoctorTaskEmptyState();
        bindStandalonePasswordMeters();
        bindAuthActionButtons();
        initEmailVerificationFlow();
        const activeChartButton = document.querySelector("[data-chart-button].bh-btn-primary[data-patient-id]");
        if (activeChartButton) {
            syncOpenChartButtons(activeChartButton.dataset.patientId);
        }
    }

    function replaceLivePageRootWithHtml(html, options = {}) {
        const currentRoot = document.querySelector("[data-live-page-root]");
        if (!currentRoot) return null;
        const preserveScroll = options.preserveScroll !== false;
        const scrollPosition = window.scrollY || 0;
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const nextRoot = doc.querySelector("[data-live-page-root]");
        if (!nextRoot) return null;
        currentRoot.replaceWith(nextRoot);
        rehydrateLivePageFeatures();
        if (preserveScroll) {
            window.requestAnimationFrame(() => {
                window.scrollTo({ top: scrollPosition, behavior: "auto" });
            });
        }
        return nextRoot;
    }

    function replaceLiveSectionsWithHtml(html, selectors = [], options = {}) {
        if (!selectors.length) return [];
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const replaced = [];
        selectors.forEach((selector) => {
            const currentNodes = Array.from(document.querySelectorAll(selector));
            const nextNodes = Array.from(doc.querySelectorAll(selector));
            if (!currentNodes.length || currentNodes.length !== nextNodes.length) return;
            currentNodes.forEach((currentNode, index) => {
                if (!options.force && hasProtectedLiveRefreshState(currentNode)) {
                    return;
                }
                const nextNode = nextNodes[index];
                if (!nextNode) return;
                currentNode.replaceWith(nextNode);
                replaced.push(nextNode);
            });
        });
        if (replaced.length) {
            rehydrateLivePageFeatures();
        }
        return replaced;
    }

    async function refreshLiveSections(selectors = [], options = {}) {
        const normalized = Array.isArray(selectors) ? selectors.filter(Boolean) : parseRefreshSelectors(selectors);
        if (!normalized.length) return [];
        try {
            const response = await fetch(window.location.href, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            if (!response.ok) return [];
            const html = await response.text();
            return replaceLiveSectionsWithHtml(html, normalized, options);
        } catch (_) {
            return [];
        }
    }

    let liveRootRefreshPending = false;
    let liveRootRefreshRetryTimer = null;

    function isFieldDirty(field) {
        if (!(field instanceof HTMLElement) || field.disabled) return false;
        if (field.matches("input[type='hidden'], input[type='submit'], input[type='button'], input[type='reset'], button")) {
            return false;
        }
        if (field instanceof HTMLInputElement) {
            if (field.type === "checkbox" || field.type === "radio") {
                return field.checked !== field.defaultChecked;
            }
            if (field.type === "file") {
                return field.files && field.files.length > 0;
            }
            return field.value !== field.defaultValue;
        }
        if (field instanceof HTMLTextAreaElement) {
            return field.value !== field.defaultValue;
        }
        if (field instanceof HTMLSelectElement) {
            return Array.from(field.options).some((option) => option.selected !== option.defaultSelected);
        }
        return false;
    }

    function isFormInteractionProtected(form) {
        if (!(form instanceof HTMLFormElement)) return false;
        if (form.dataset.liveRefreshAllow === "1") return false;
        if (form.dataset.liveRefreshProtect === "0") return false;
        if (form.matches("[data-async-context-form], [data-async-status-form]")) return false;
        const activeElement = document.activeElement;
        if (activeElement instanceof HTMLElement && form.contains(activeElement)) {
            return true;
        }
        if (form.dataset.liveDirty === "1") {
            return true;
        }
        return Array.from(form.elements || []).some((field) => isFieldDirty(field));
    }

    function hasProtectedLiveRefreshState(root) {
        return Array.from(root.querySelectorAll("form")).some((form) => isFormInteractionProtected(form));
    }

    function syncFormDirtyState(form) {
        if (!(form instanceof HTMLFormElement)) return;
        if (Array.from(form.elements || []).some((field) => isFieldDirty(field))) {
            form.dataset.liveDirty = "1";
        } else {
            delete form.dataset.liveDirty;
        }
    }

    function queuePendingLiveRootRefresh() {
        if (!liveRootRefreshPending || liveRootRefreshRetryTimer) return;
        liveRootRefreshRetryTimer = window.setTimeout(async () => {
            liveRootRefreshRetryTimer = null;
            const root = document.querySelector("[data-live-page-root]");
            if (!root || hasProtectedLiveRefreshState(root)) {
                queuePendingLiveRootRefresh();
                return;
            }
            if (typeof refreshCurrentPageLiveRoot === "function") {
                await refreshCurrentPageLiveRoot();
            }
        }, 900);
    }

    document.addEventListener("input", (event) => {
        const form = event.target instanceof HTMLElement ? event.target.closest("form") : null;
        if (!form) return;
        syncFormDirtyState(form);
        queuePendingLiveRootRefresh();
    });

    document.addEventListener("change", (event) => {
        const form = event.target instanceof HTMLElement ? event.target.closest("form") : null;
        if (!form) return;
        syncFormDirtyState(form);
        queuePendingLiveRootRefresh();
    });

    document.addEventListener("focusout", (event) => {
        const form = event.target instanceof HTMLElement ? event.target.closest("form") : null;
        if (!form) return;
        window.setTimeout(() => {
            syncFormDirtyState(form);
            queuePendingLiveRootRefresh();
        }, 0);
    });

    document.addEventListener("reset", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        window.setTimeout(() => {
            delete form.dataset.liveDirty;
            queuePendingLiveRootRefresh();
        }, 0);
    });

    async function refreshCurrentPageLiveRootImpl(options = {}) {
        const root = document.querySelector("[data-live-page-root]");
        if (!root) return null;
        const force = options === true || (typeof options === "object" && options?.force === true);
        if (!force && hasProtectedLiveRefreshState(root)) {
            liveRootRefreshPending = true;
            queuePendingLiveRootRefresh();
            return root;
        }
        try {
            liveRootRefreshPending = false;
            if (liveRootRefreshRetryTimer) {
                window.clearTimeout(liveRootRefreshRetryTimer);
                liveRootRefreshRetryTimer = null;
            }
            const scrollPosition = window.scrollY || 0;
            const response = await fetch(window.location.href, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" });
            if (!response.ok) return null;
            const html = await response.text();
            const nextRoot = replaceLivePageRootWithHtml(html);
            if (!nextRoot) return null;
            return nextRoot;
        } catch (_) {
            return null;
        }
    }

    refreshCurrentPageLiveRoot = refreshCurrentPageLiveRootImpl;

    function doctorTaskEmptyStateMarkup() {
        return `
            <div class="empty-state p-4 text-center" data-doctor-task-empty>
                <div class="empty-illustration mx-auto mb-3"><i class="bi bi-check2-all fs-2"></i></div>
                <div class="fw-semibold">All follow-up tasks are complete</div>
                <div class="text-secondary small">New clinical tasks will appear here as care coordination continues.</div>
            </div>
        `;
    }

    function syncDoctorTaskEmptyState() {
        const list = document.getElementById("doctorTaskList");
        if (!list) return;
        const cards = list.querySelectorAll("[data-doctor-task-card]");
        let emptyNode = list.querySelector("[data-doctor-task-empty]");
        if (!cards.length) {
            if (!emptyNode) {
                list.insertAdjacentHTML("beforeend", doctorTaskEmptyStateMarkup());
            }
            return;
        }
        if (emptyNode) {
            emptyNode.remove();
        }
    }

    function renderCommunicationMessage(message, currentUserId) {
        const isLoading = message.kind === "assistant_loading";
        const toneClass = isLoading
            ? "is-loading"
            : message.kind === "assistant"
                ? "is-assistant"
                : String(message.sender_id || "") === String(currentUserId || "")
                    ? "is-user"
                    : "is-other";
        const body = isLoading
            ? `<div class="communications-typing"><span></span><span></span><span></span></div>`
            : `<div class="communications-bubble-body">${escapeHtml(message.body || "").replace(/\n/g, "<br>")}</div>`;
        return `
            <div class="communications-bubble ${toneClass}" data-communication-message-id="${escapeHtml(message.id)}">
                <div class="communications-bubble-role">${escapeHtml(message.sender || "BayAfya")}</div>
                ${body}
            </div>
        `;
    }

    function formatTypingUsers(names) {
        if (!names.length) return "Someone is typing...";
        if (names.length === 1) return `${names[0]} is typing...`;
        if (names.length === 2) return `${names[0]} and ${names[1]} are typing...`;
        return `${names[0]}, ${names[1]}, and ${names.length - 2} others are typing...`;
    }

    function initStaffCommunications() {
        if (typeof window.__bayafyaCommunicationsCleanup === "function") {
            try {
                window.__bayafyaCommunicationsCleanup();
            } catch (_) {}
        }
        const page = document.querySelector("[data-communications-page]");
        if (!page) return;

        const conversationId = page.dataset.conversationId;
        const currentUserId = page.dataset.currentUserId;
        const messagesEndpoint = page.dataset.messagesEndpoint;
        const sendEndpoint = page.dataset.sendEndpoint;
        const messageStream = document.getElementById("staffConversationMessages");
        const form = page.querySelector("[data-communication-form]");
        const input = page.querySelector("[data-communication-input]");
        const loadingState = page.querySelector("[data-communications-loading-state]");
        const typingIndicator = page.querySelector("[data-communications-typing-indicator]");
        const typingCopy = page.querySelector("[data-communications-typing-copy]");
        const toolDrawer = page.querySelector("[data-communications-tool-drawer]");
        const toolTriggers = Array.from(page.querySelectorAll("[data-communications-tool-trigger]"));
        const toolPanels = toolDrawer ? Array.from(toolDrawer.querySelectorAll("[data-communications-tool-panel]")) : [];
        const toolCloseButtons = Array.from(page.querySelectorAll("[data-communications-tool-close]"));
        const communicationsRoot = document.querySelector("[data-communications-root]");
        const threadLinks = Array.from(document.querySelectorAll("[data-communications-thread-link]"));
        const hasConversationWorkspace = Boolean(conversationId && messageStream && form && input && messagesEndpoint && sendEndpoint);

        let communicationsPollingTimer = null;
        let latestMessageId = 0;
        let hasInitializedPoll = false;
        let communicationSocket = null;
        let inboxSocket = null;
        let websocketConnected = false;
        let communicationsFallbackNotified = false;
        let inboxSocketConnected = false;
        let typingTimer = null;
        let typingSent = false;
        const activeTypers = new Map();

        const setToolPanel = (name = "") => {
            if (!toolDrawer) return;
            const normalized = String(name || "").trim();
            if (!normalized) {
                toolPanels.forEach((panel) => panel.classList.add("d-none"));
                toolDrawer.classList.add("d-none");
                return;
            }
            toolDrawer.classList.remove("d-none");
            toolPanels.forEach((panel) => {
                panel.classList.toggle("d-none", panel.dataset.communicationsToolPanel !== normalized);
            });
        };

        toolTriggers.forEach((button) => {
            if (button.dataset.toolBound === "1") return;
            button.dataset.toolBound = "1";
            button.addEventListener("click", () => {
                setToolPanel(button.dataset.communicationsToolTrigger || "");
                if (toolDrawer) {
                    toolDrawer.scrollIntoView({ behavior: "smooth", block: "start" });
                }
            });
        });
        toolCloseButtons.forEach((button) => {
            if (button.dataset.toolCloseBound === "1") return;
            button.dataset.toolCloseBound = "1";
            button.addEventListener("click", () => {
                setToolPanel("");
            });
        });
        setToolPanel("");

        const cleanupCommunications = () => {
            if (communicationSocket && communicationSocket.readyState < WebSocket.CLOSING) {
                try {
                    communicationSocket.close();
                } catch (_) {}
            }
            if (inboxSocket && inboxSocket.readyState < WebSocket.CLOSING) {
                try {
                    inboxSocket.close();
                } catch (_) {}
            }
            if (communicationsPollingTimer) {
                window.clearInterval(communicationsPollingTimer);
                communicationsPollingTimer = null;
            }
            if (typingTimer) {
                window.clearTimeout(typingTimer);
                typingTimer = null;
            }
        };
        window.__bayafyaCommunicationsCleanup = cleanupCommunications;

        const setConversationLoading = (loading) => {
            if (!loadingState) return;
            loadingState.classList.toggle("d-none", !loading);
        };

        const setActiveThread = (nextConversationId) => {
            threadLinks.forEach((link) => {
                const isActive = String(link.dataset.conversationId || "") === String(nextConversationId || "");
                link.classList.toggle("is-active", isActive);
            });
        };

        const updateTypingIndicator = () => {
            if (!typingIndicator || !typingCopy) return;
            const names = Array.from(activeTypers.values());
            typingIndicator.classList.toggle("d-none", names.length === 0);
            typingCopy.textContent = formatTypingUsers(names);
        };

        const applyThreadUpdate = (payload, { incrementUnread = false } = {}) => {
            if (!payload || !payload.conversation_id) return;
            const link = document.querySelector(`[data-communications-thread-link][data-conversation-id="${CSS.escape(String(payload.conversation_id))}"]`);
            if (!link) return;
            const previewNode = link.querySelector("[data-thread-preview]");
            const unreadNode = link.querySelector("[data-thread-unread]");
            const titleNode = link.querySelector("[data-thread-title]");
            const subtitleNode = link.querySelector("[data-thread-subtitle]");
            if (titleNode && payload.title) titleNode.textContent = payload.title;
            if (subtitleNode && payload.subtitle) subtitleNode.textContent = payload.subtitle;
            if (previewNode && payload.preview) previewNode.textContent = payload.preview;
            if (unreadNode) {
                let unread = Number(payload.unread_count ?? 0);
                if (incrementUnread) unread = Math.max(unread, (Number(unreadNode.textContent || "0") || 0) + 1);
                if (String(payload.conversation_id) === String(conversationId || "")) unread = 0;
                unreadNode.textContent = unread > 0 ? String(unread) : "";
                unreadNode.classList.toggle("d-none", unread <= 0);
            }
            const sidebar = link.parentElement;
            if (sidebar && sidebar.firstElementChild !== link) {
                sidebar.prepend(link);
            }
        };

        const reloadCommunicationsWorkspace = async (nextConversationId = "") => {
            cleanupCommunications();
            setActiveThread(nextConversationId);
            setConversationLoading(true);
            const nextUrl = new URL(window.location.href);
            if (nextConversationId) {
                nextUrl.searchParams.set("conversation", nextConversationId);
            } else {
                nextUrl.searchParams.delete("conversation");
            }
            const response = await fetch(nextUrl.toString(), {
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!response.ok) {
                setConversationLoading(false);
                appendToast("Communications updated", "The workspace could not be refreshed right now.", "warning");
                return;
            }
            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const nextRoot = doc.querySelector("[data-communications-root]");
            if (!nextRoot || !communicationsRoot) {
                window.location.href = nextUrl.toString();
                return;
            }
            communicationsRoot.replaceWith(nextRoot);
            window.history.replaceState({}, "", nextUrl.toString());
            initStaffCommunications();
        };

        threadLinks.forEach((link) => {
            if (link.dataset.threadBound === "1") return;
            link.dataset.threadBound = "1";
            link.addEventListener("click", (event) => {
                const nextConversationId = link.dataset.conversationId || "";
                if (!nextConversationId || String(nextConversationId) === String(conversationId || "")) return;
                event.preventDefault();
                reloadCommunicationsWorkspace(nextConversationId);
            });
        });

        document.querySelectorAll("[data-communications-async-form]").forEach((asyncForm) => {
            if (asyncForm.dataset.communicationsSubmitBound === "1") return;
            asyncForm.dataset.communicationsSubmitBound = "1";
            asyncForm.addEventListener("submit", (event) => {
                event.preventDefault();
                clearInlineFormErrors(asyncForm);
                const button = asyncForm.querySelector("[data-auth-submit]") || asyncForm.querySelector("button[type='submit']");
                withBusyButton(button, "", async () => {
                    const response = await fetch(getFormActionUrl(asyncForm), {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": asyncForm.querySelector("[name=csrfmiddlewaretoken]")?.value || ""
                        },
                        body: new FormData(asyncForm)
                    });
                    const payload = await response.json().catch(() => ({}));
                    if (!response.ok || payload.ok === false) {
                        showInlineFormErrors(asyncForm, payload.errors || {});
                        appendToast("Update failed", payload.message || "Please review the highlighted fields.", "danger");
                        return;
                    }
                    appendToast("Communications updated", payload.message || "Conversation workspace updated.", "success");
                    await reloadCommunicationsWorkspace(payload.conversation_id || "");
                });
            });
        });

        const initInboxSocket = () => {
            const protocol = window.location.protocol === "https:" ? "wss" : "ws";
            try {
                inboxSocket = new WebSocket(`${protocol}://${window.location.host}/ws/communications/inbox/`);
            } catch (_) {
                return;
            }
            inboxSocket.addEventListener("open", () => {
                inboxSocketConnected = true;
            });
            inboxSocket.addEventListener("message", (event) => {
                const payload = JSON.parse(event.data || "{}");
                applyThreadUpdate(payload);
            });
            inboxSocket.addEventListener("close", () => {
                inboxSocketConnected = false;
            });
            inboxSocket.addEventListener("error", () => {
                inboxSocketConnected = false;
            });
        };

        initInboxSocket();

        if (!hasConversationWorkspace) {
            return;
        }

        const scrollToBottom = () => {
            window.requestAnimationFrame(() => {
                messageStream.scrollTop = messageStream.scrollHeight;
            });
        };

        const removeLoadingBubbles = () => {
            messageStream.querySelectorAll(".communications-bubble.is-loading").forEach((node) => node.remove());
        };

        const appendMessage = (message) => {
            if (!message) return;
            if (message.kind !== "assistant_loading") {
                removeLoadingBubbles();
            }
            const duplicate = messageStream.querySelector(`[data-communication-message-id="${CSS.escape(String(message.id))}"]`);
            if (duplicate) return;
            const emptyState = messageStream.querySelector(".empty-state");
            if (emptyState) emptyState.remove();
            messageStream.insertAdjacentHTML("beforeend", renderCommunicationMessage(message, currentUserId));
            scrollToBottom();
        };

        latestMessageId = Array.from(messageStream.querySelectorAll("[data-communication-message-id]"))
            .map((node) => Number(node.getAttribute("data-communication-message-id")) || 0)
            .reduce((maxId, value) => Math.max(maxId, value), 0);

        const syncMessages = async (silent = false) => {
            try {
                const response = await fetch(`${messagesEndpoint}?since_id=${latestMessageId}`, {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                if (!response.ok) return;
                const payload = await response.json();
                if (!hasInitializedPoll) {
                    latestMessageId = payload.latest_id || latestMessageId;
                    hasInitializedPoll = true;
                    return;
                }
                (payload.messages || []).forEach((message) => {
                    appendMessage(message);
                    latestMessageId = Math.max(latestMessageId, Number(message.id) || latestMessageId);
                });
                if (payload.thread) {
                    applyThreadUpdate(payload.thread);
                }
            } catch (_) {
                if (!silent && !communicationsFallbackNotified) {
                    communicationsFallbackNotified = true;
                    appendToast("Communications delayed", "Live conversation updates are temporarily using background refresh.", "info");
                }
            }
        };

        const startPollingFallback = () => {
            syncMessages(true);
            communicationsPollingTimer = window.setInterval(() => {
                if (document.hidden) return;
                syncMessages(true);
            }, 5000);
        };

        const initCommunicationSocket = () => {
            const protocol = window.location.protocol === "https:" ? "wss" : "ws";
            try {
                communicationSocket = new WebSocket(`${protocol}://${window.location.host}/ws/communications/${conversationId}/`);
            } catch (_) {
                startPollingFallback();
                return;
            }

            communicationSocket.addEventListener("open", () => {
                websocketConnected = true;
                syncMessages(true);
            });

            communicationSocket.addEventListener("message", (event) => {
                const payload = JSON.parse(event.data || "{}");
                if (payload.typing) {
                    const typing = payload.typing;
                    if (typing.is_typing) {
                        activeTypers.set(String(typing.user_id), typing.name || "Someone");
                    } else {
                        activeTypers.delete(String(typing.user_id));
                    }
                    updateTypingIndicator();
                    return;
                }
                if (!payload.message) return;
                appendMessage(payload.message);
                latestMessageId = Math.max(latestMessageId, Number(payload.message.id) || latestMessageId);
                if (payload.message.kind !== "assistant_loading") {
                    applyThreadUpdate(
                        {
                            conversation_id: conversationId,
                            preview: payload.message.body || "New update",
                            unread_count: 0,
                        }
                    );
                }
            });

            communicationSocket.addEventListener("close", () => {
                websocketConnected = false;
                startPollingFallback();
            });

            communicationSocket.addEventListener("error", () => {
                websocketConnected = false;
            });
        };

        scrollToBottom();
        initCommunicationSocket();

        const sendTypingState = (isTyping) => {
            if (!websocketConnected || communicationSocket?.readyState !== WebSocket.OPEN) return;
            communicationSocket.send(JSON.stringify({ type: "typing", is_typing: isTyping }));
        };

        const queueTypingStop = () => {
            if (typingTimer) {
                window.clearTimeout(typingTimer);
            }
            typingTimer = window.setTimeout(() => {
                if (!typingSent) return;
                typingSent = false;
                sendTypingState(false);
            }, 1600);
        };

        input.addEventListener("input", () => {
            const hasValue = Boolean((input.value || "").trim());
            if (hasValue && !typingSent) {
                typingSent = true;
                sendTypingState(true);
            }
            if (!hasValue && typingSent) {
                typingSent = false;
                sendTypingState(false);
                if (typingTimer) window.clearTimeout(typingTimer);
                return;
            }
            if (hasValue) queueTypingStop();
        });
        input.addEventListener("blur", () => {
            if (!typingSent) return;
            typingSent = false;
            sendTypingState(false);
            if (typingTimer) window.clearTimeout(typingTimer);
        });

        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const value = input.value.trim();
            if (!value) return;
            withBusyButton(form.querySelector("button[type='submit']"), "", async () => {
                try {
                    if (typingSent) {
                        typingSent = false;
                        sendTypingState(false);
                    }
                    if (websocketConnected && communicationSocket?.readyState === WebSocket.OPEN) {
                        communicationSocket.send(JSON.stringify({ message: value }));
                        applyThreadUpdate({
                            conversation_id: conversationId,
                            preview: value,
                            unread_count: 0,
                        });
                        input.value = "";
                        input.focus();
                        return;
                    }
                    const formData = new FormData();
                    formData.append("message", value);
                    formData.append("csrfmiddlewaretoken", document.querySelector("[name=csrfmiddlewaretoken]")?.value || "");
                    const response = await fetch(sendEndpoint, {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]")?.value || ""
                        },
                        body: formData
                    });
                    const payload = await response.json().catch(() => ({}));
                    if (!response.ok || payload.ok === false) {
                        appendToast("Messaging unavailable", payload.message || "The conversation could not be updated right now.", "danger");
                        return;
                    }
                    if (payload.message) {
                        appendMessage(payload.message);
                        latestMessageId = Math.max(latestMessageId, Number(payload.message.id) || latestMessageId);
                        applyThreadUpdate({
                            conversation_id: conversationId,
                            preview: payload.message.body || value,
                            unread_count: 0,
                        });
                    }
                    input.value = "";
                    input.focus();
                    if (payload.assistant_message) {
                        appendMessage(payload.assistant_message);
                        latestMessageId = Math.max(latestMessageId, Number(payload.assistant_message.id) || latestMessageId);
                        applyThreadUpdate({
                            conversation_id: conversationId,
                            preview: payload.assistant_message.body,
                            unread_count: 0,
                        });
                    }
                } catch (_) {
                    appendToast("Messaging unavailable", "The conversation could not be updated right now.", "danger");
                }
            });
        });
    }

    const bayafyaWatchTimers = new WeakMap();

    function initBayafyaWatch() {
        document.querySelectorAll(".bayafya-watch").forEach((card) => {
            const list = card.querySelector("[data-bayafya-watch-list]");
            const items = Array.from(card.querySelectorAll("[data-bayafya-watch-item]"));
            const toggle = card.querySelector("[data-bayafya-watch-toggle]");
            const refreshButton = card.querySelector("[data-bayafya-watch-refresh]");
            const dismissUrl = card.dataset.watchDismissUrl;
            const existingTimer = bayafyaWatchTimers.get(card);
            if (existingTimer) {
                window.clearInterval(existingTimer);
            }
            if (refreshButton && refreshButton.dataset.refreshBound !== "1") {
                refreshButton.dataset.refreshBound = "1";
                refreshButton.addEventListener("click", () => {
                    withBusyButton(refreshButton, "", async () => {
                        if (typeof refreshLiveDashboardState === "function") {
                            const payload = await refreshLiveDashboardState();
                            if (!payload) {
                                appendToast("BayAfya watch", "Recent watch items could not be refreshed right now.", "warning");
                            }
                            return;
                        }
                        appendToast("BayAfya watch", "Live watch refresh is not available on this screen right now.", "info");
                    });
                });
            }
            if (!list || !items.length) return;

            let activeIndex = Math.max(0, items.findIndex((item) => item.hasAttribute("data-watch-active")));
            if (activeIndex < 0) activeIndex = 0;

            const setActive = (index) => {
                items.forEach((item, itemIndex) => {
                    item.classList.toggle("is-active", itemIndex === index);
                });
            };

            setActive(activeIndex);

            const rotationTimer = window.setInterval(() => {
                if (card.classList.contains("is-expanded") || items.length <= 1) return;
                activeIndex = (activeIndex + 1) % items.length;
                setActive(activeIndex);
            }, 8800);
            bayafyaWatchTimers.set(card, rotationTimer);

            toggle?.addEventListener("click", () => {
                const expanded = card.classList.toggle("is-expanded");
                toggle.textContent = expanded ? "Collapse" : "Show more";
                toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
                if (!expanded) {
                    setActive(activeIndex);
                }
            });

            card.querySelectorAll("[data-watch-dismiss]").forEach((button) => {
                if (button.dataset.dismissBound === "1") return;
                button.dataset.dismissBound = "1";
                button.addEventListener("click", async () => {
                    const signalId = button.dataset.watchDismiss;
                    const itemNode = button.closest("[data-bayafya-watch-item]");
                    if (!dismissUrl || !signalId || !itemNode) return;
                    try {
                        const formData = new FormData();
                        formData.append("signal_id", signalId);
                        const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
                        const response = await fetch(dismissUrl, {
                            method: "POST",
                            headers: {
                                "X-Requested-With": "XMLHttpRequest",
                                "X-CSRFToken": csrf,
                            },
                            body: formData,
                        });
                        if (!response.ok) return;
                        itemNode.classList.add("is-hidden");
                        window.setTimeout(() => {
                            itemNode.remove();
                            applyBayafyaWatchItems(Array.from(card.querySelectorAll("[data-bayafya-watch-item]")).map((node) => ({
                                id: node.dataset.watchId,
                                title: node.querySelector(".fw-semibold")?.textContent || "BayAfya watch",
                                tone: node.className.includes("tone-danger") ? "danger" : node.className.includes("tone-warning") ? "warning" : "primary",
                                detail: node.querySelector(".text-secondary.small")?.textContent || "",
                                meta: node.querySelector(".text-secondary.small.mt-2")?.textContent || "",
                            })));
                        }, 220);
                    } catch (_) {
                        return;
                    }
                });
            });
        });
    }

    function slugifyCode(value) {
        return (value || "")
            .toString()
            .toLowerCase()
            .trim()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 48);
    }

    function initMobileBottomNav() {
        const nav = document.querySelector("[data-mobile-bottom-nav]");
        const inner = nav?.querySelector("[data-mobile-bottom-nav-inner]");
        const hintLabel = nav?.querySelector("[data-mobile-bottom-nav-hint-label]");
        const hintIcon = nav?.querySelector("[data-mobile-bottom-nav-hint-icon]");
        if (!nav || !inner) return;

        const syncState = () => {
            const overflow = inner.scrollWidth - inner.clientWidth > 12;
            const atStart = inner.scrollLeft <= 12;
            const atEnd = inner.scrollLeft + inner.clientWidth >= inner.scrollWidth - 12;
            nav.classList.toggle("is-scrollable", overflow);
            nav.classList.toggle("is-at-start", !overflow || atStart);
            nav.classList.toggle("is-at-end", !overflow || atEnd);
            nav.classList.toggle("is-at-middle", overflow && !atStart && !atEnd);
            if (hintLabel && hintIcon) {
                if (!overflow) {
                    hintLabel.textContent = "More";
                    hintIcon.className = "bi bi-chevron-double-right";
                } else if (atEnd) {
                    hintLabel.textContent = "Back";
                    hintIcon.className = "bi bi-chevron-double-left";
                } else if (atStart) {
                    hintLabel.textContent = "More";
                    hintIcon.className = "bi bi-chevron-double-right";
                } else {
                    hintLabel.textContent = "Scroll";
                    hintIcon.className = "bi bi-arrow-left-right";
                }
            }
        };

        syncState();
        inner.addEventListener("scroll", syncState, { passive: true });
        window.addEventListener("resize", syncState);
        window.setTimeout(syncState, 120);
    }

    function syncFilteredBedOptions(sourceSelect) {
        if (!sourceSelect) return;
        const targetId = sourceSelect.dataset.bedFilterTarget;
        if (!targetId) return;
        const target = document.getElementById(targetId);
        if (!target) return;

        let options = [];
        try {
            options = JSON.parse(target.dataset.bedOptions || "[]");
        } catch (_) {
            options = [];
        }

        const selectedWard = String(sourceSelect.value || "");
        const currentValue = String(target.value || "");
        const filteredOptions = selectedWard
            ? options.filter((item) => String(item.ward) === selectedWard)
            : options;

        target.innerHTML = "";
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = filteredOptions.length ? "---------" : "No beds available for this ward";
        target.appendChild(placeholder);

        filteredOptions.forEach((item) => {
            const option = document.createElement("option");
            option.value = item.value;
            option.textContent = item.label;
            if (String(item.value) === currentValue) {
                option.selected = true;
            }
            target.appendChild(option);
        });

        if (!filteredOptions.some((item) => String(item.value) === currentValue)) {
            target.value = "";
        }
    }

    function initAdmissionDependentSelectors(root = document) {
        root.querySelectorAll("select[data-bed-filter-target]").forEach((select) => {
            const sync = () => {
                if (select.dataset.admissionWardMap) {
                    let wardMap = {};
                    try {
                        wardMap = JSON.parse(select.dataset.admissionWardMap || "{}");
                    } catch (_) {
                        wardMap = {};
                    }
                    const targetWard = root.querySelector("#id_target_ward");
                    const mappedWard = wardMap[String(select.value || "")];
                    if (targetWard && mappedWard) {
                        targetWard.value = String(mappedWard);
                        syncFilteredBedOptions(targetWard);
                    }
                }
                syncFilteredBedOptions(select);
            };

            if (select.dataset.bedFilterBound !== "1") {
                select.addEventListener("change", sync);
                select.dataset.bedFilterBound = "1";
            }
            sync();
        });
    }

    function initAdmissionActionWorkspace() {
        const workspace = document.querySelector("[data-admission-workspace]");
        if (!workspace) return;

        const titleNode = workspace.querySelector("[data-admission-workspace-title]");
        const panels = Array.from(workspace.querySelectorAll("[data-admission-panel]"));
        const closeButton = workspace.querySelector("[data-admission-workspace-close]");
        const titles = {
            admit: "Admit patient",
            transfer: "Move patient to another bed",
            discharge: "Finalize patient release",
            follow_up: "Schedule post-discharge follow-up",
        };

        const openPanel = (key) => {
            let found = false;
            panels.forEach((panel) => {
                const isActive = panel.dataset.admissionPanel === key;
                panel.classList.toggle("d-none", !isActive);
                found = found || isActive;
            });
            if (!found) return;
            workspace.classList.remove("d-none");
            if (titleNode) {
                titleNode.textContent = titles[key] || "Admission workflow";
            }
            window.requestAnimationFrame(() => {
                workspace.scrollIntoView({ behavior: "smooth", block: "start" });
            });
        };

        document.querySelectorAll("[data-admission-workspace-target]").forEach((trigger) => {
            trigger.addEventListener("click", (event) => {
                event.preventDefault();
                openPanel(trigger.dataset.admissionWorkspaceTarget);
            });
        });

        closeButton?.addEventListener("click", () => {
            workspace.classList.add("d-none");
            panels.forEach((panel) => panel.classList.add("d-none"));
        });
    }

    async function refreshAdmissionDashboardRoot() {
        const currentRoot = document.querySelector("[data-admission-dashboard-root]");
        if (!currentRoot) return false;

        const response = await fetch(window.location.pathname, {
            headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        if (!response.ok) return false;

        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const nextRoot = doc.querySelector("[data-admission-dashboard-root]");
        if (!nextRoot) return false;

        currentRoot.replaceWith(nextRoot);
        nextRoot.querySelectorAll("select[data-autocomplete]").forEach(enhanceAutocompleteSelect);
        initAdmissionActionWorkspace();
        initAdmissionDependentSelectors(nextRoot);
        enhanceScrollableLists();
        applySmartFillRows();
        return true;
    }

    function hydrateAdmissionDashboardHtml(html) {
        if (!html) return false;
        const currentRoot = document.querySelector("[data-admission-dashboard-root]");
        if (!currentRoot) return false;
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const nextRoot = doc.querySelector("[data-admission-dashboard-root]");
        if (!nextRoot) return false;
        currentRoot.replaceWith(nextRoot);
        nextRoot.querySelectorAll("select[data-autocomplete]").forEach(enhanceAutocompleteSelect);
        initAdmissionActionWorkspace();
        initAdmissionDependentSelectors(nextRoot);
        enhanceScrollableLists();
        applySmartFillRows();
        return true;
    }

    function initRotatingCardStacks() {
        document.querySelectorAll("[data-rotating-cards]").forEach((stack) => {
            const cards = Array.from(stack.querySelectorAll("[data-rotating-card]"));
            if (cards.length <= 1) return;

            if (stack._rotationTimer) {
                window.clearInterval(stack._rotationTimer);
            }

            let activeIndex = cards.findIndex((card) => card.classList.contains("is-active"));
            if (activeIndex < 0) activeIndex = 0;

            const activate = (index) => {
                cards.forEach((card, cardIndex) => {
                    const isActive = cardIndex === index;
                    card.classList.toggle("is-active", isActive);
                    card.classList.toggle("d-none", !isActive);
                });
            };

            activate(activeIndex);
            stack._rotationTimer = window.setInterval(() => {
                activeIndex = (activeIndex + 1) % cards.length;
                activate(activeIndex);
            }, 11000);
        });
    }

    function defaultAssistantMode() {
        const savedMode = window.sessionStorage.getItem("bayafya-assistant-mode");
        if (savedMode) return savedMode;
        const activeTab = assistantModeBar?.querySelector("[data-assistant-mode].is-active");
        if (activeTab?.dataset?.assistantMode) return activeTab.dataset.assistantMode;
        const firstTab = assistantModeBar?.querySelector("[data-assistant-mode]");
        if (firstTab?.dataset?.assistantMode) return firstTab.dataset.assistantMode;
        const pathname = window.location.pathname.toLowerCase();
        if (pathname.includes("mental-health")) return "mental_health";
        return "patient_chart";
    }

    function currentAssistantContext() {
        return assistantMode || defaultAssistantMode();
    }

    function syncAssistantModeTabs() {
        if (!assistantModeBar) return;
        assistantModeBar.querySelectorAll("[data-assistant-mode]").forEach((tab) => {
            const isActive = tab.dataset.assistantMode === assistantMode;
            tab.classList.toggle("is-active", isActive);
            tab.setAttribute("aria-selected", isActive ? "true" : "false");
        });
    }

    function syncAssistantWorkspaceDots(index) {
        if (!assistantWorkspaceDots) return;
        assistantWorkspaceDots.querySelectorAll("[data-assistant-dot]").forEach((dot) => {
            dot.classList.toggle("is-active", Number(dot.dataset.assistantDot) === index);
        });
    }

    function scrollAssistantWorkspaceTo(index) {
        if (!assistantWorkspaceRail) return;
        const width = assistantWorkspaceRail.clientWidth || 0;
        assistantWorkspaceRail.scrollTo({
            left: width * index,
            behavior: "smooth",
        });
        syncAssistantWorkspaceDots(index);
    }

    function setAssistantChatCompactMode(enabled) {
        document.body.classList.toggle("assistant-chat-compact", Boolean(enabled));
    }

    function appendAssistantMessage(role, text) {
        if (!assistantChatStream || !text) return;
        const bubble = document.createElement("div");
        bubble.className = `assistant-chat-bubble ${role === "assistant" ? "is-assistant" : "is-user"}`;
        bubble.innerHTML = `
            <div class="assistant-chat-role">${role === "assistant" ? `${platformName} Assistant` : "You"}</div>
            <div class="assistant-chat-copy">${text}</div>
        `;
        assistantChatStream.appendChild(bubble);
        assistantChatStream.scrollTop = assistantChatStream.scrollHeight;
        if (assistantPanel && assistantPanel.classList.contains("show")) {
            setAssistantChatCompactMode(true);
        }
        return bubble;
    }

    function appendAssistantLoadingBubble() {
        if (!assistantChatStream) return null;
        const bubble = document.createElement("div");
        bubble.className = "assistant-chat-bubble is-assistant is-loading";
        bubble.innerHTML = `
            <div class="assistant-chat-role">${platformName} Assistant</div>
            <div class="assistant-chat-copy is-muted">
                <span class="assistant-typing" aria-label="Assistant is thinking">
                    <span></span><span></span><span></span>
                </span>
            </div>
        `;
        assistantChatStream.appendChild(bubble);
        assistantChatStream.scrollTop = assistantChatStream.scrollHeight;
        return bubble;
    }

    function renderAssistantHistoryLoader() {
        if (!assistantChatStream) return;
        clearElement(assistantChatStream);
        const loader = document.createElement("div");
        loader.className = "assistant-history-loader";
        loader.innerHTML = `
            <div class="assistant-chat-bubble is-assistant is-loading">
                <div class="assistant-chat-role">${platformName} Assistant</div>
                <div class="assistant-chat-copy is-muted d-flex align-items-center gap-2">
                    <span class="spinner-border spinner-border-sm" aria-hidden="true"></span>
                    <span>Loading recent conversation...</span>
                </div>
            </div>
        `;
        assistantChatStream.appendChild(loader);
    }

    function assistantModeLabel(mode) {
        const labels = {
            patient_chart: "Patient chart",
            triage: "Triage",
            mental_health: "Mental health",
            hospital_operations: "Hospital operations",
        };
        return labels[mode] || "Care workspace";
    }

    function renderAssistantEmptyState() {
        if (!assistantChatStream) return;
        clearElement(assistantChatStream);
        const modeLabel = assistantModeLabel(currentAssistantContext());
        const emptyState = document.createElement("div");
        emptyState.className = "assistant-empty-state";
        emptyState.innerHTML = `
            <div class="assistant-empty-hero">
                <div class="assistant-empty-icon"><i class="bi bi-stars"></i></div>
                <div>
                    <div class="assistant-empty-title">Start a fresh ${modeLabel.toLowerCase()} conversation</div>
                    <div class="assistant-empty-copy">${platformName} Assistant is ready to help with summaries, next steps, and structured guidance in this workspace.</div>
                </div>
            </div>
            <div class="assistant-empty-chip-grid">
                <button class="assistant-empty-chip" type="button" data-assistant-starter="Summarize the current ${modeLabel.toLowerCase()} context.">
                    <i class="bi bi-journal-text"></i><span>Summarize this workspace</span>
                </button>
                <button class="assistant-empty-chip" type="button" data-assistant-starter="What should I do next in this ${modeLabel.toLowerCase()} workflow?">
                    <i class="bi bi-lightning-charge"></i><span>Suggest next steps</span>
                </button>
                <button class="assistant-empty-chip" type="button" data-assistant-starter="Show me the most important risks or follow-up items here.">
                    <i class="bi bi-shield-check"></i><span>Highlight important signals</span>
                </button>
            </div>
        `;
        assistantChatStream.appendChild(emptyState);
        assistantChatStream.querySelectorAll("[data-assistant-starter]").forEach((button) => {
            button.addEventListener("click", () => {
                if (!assistantPrompt) return;
                assistantPrompt.value = button.dataset.assistantStarter || "";
                autoResizeAssistantPrompt();
                assistantPrompt.focus();
            });
        });
    }

    function renderAssistantHistory(history) {
        if (!assistantChatStream) return;
        clearElement(assistantChatStream);
        const transcript = history || [];
        if (!transcript.length) {
            setAssistantChatCompactMode(false);
            renderAssistantEmptyState();
            return;
        }
        const hasUserTurn = transcript.some((entry) => entry.role === "user");
        setAssistantChatCompactMode(hasUserTurn);
        transcript.forEach((entry) => appendAssistantMessage(entry.role, entry.content));
        window.requestAnimationFrame(() => {
            assistantChatStream.scrollTop = assistantChatStream.scrollHeight;
        });
    }

    if (assistantFab) {
        assistantFab.style.position = "fixed";
        assistantFab.style.left = "auto";
        assistantFab.style.top = "auto";
    }

    function renderAssistantSuggestions(payload) {
        if (!assistantSummary || !assistantSuggestions || !assistantSafety) return;
        assistantSummary.textContent = payload.summary || "Guidance is generated from the current workspace.";
        assistantSafety.textContent = payload.safety || "Use assistant guidance together with clinical judgment.";
        if (assistantSummaryBadge) {
            assistantSummaryBadge.textContent = assistantSummary.textContent.trim() ? "1" : "0";
        }
        if (assistantSafetyBadge) {
            assistantSafetyBadge.textContent = assistantSafety.textContent.trim() ? "1" : "0";
        }
        assistantSuggestions.innerHTML = "";
        const suggestions = payload.suggestions || [];
        if (assistantSuggestionsBadge) {
            assistantSuggestionsBadge.textContent = String(suggestions.length);
        }
        if (!suggestions.length) {
            assistantSuggestions.innerHTML = '<div class="assistant-response-card small text-secondary">No suggestions available yet.</div>';
            return;
        }
        suggestions.forEach((item) => {
            const node = document.createElement("div");
            node.className = "assistant-response-card";
            const titleNode = document.createElement("div");
            titleNode.className = "assistant-response-title mb-1";
            titleNode.textContent = "Suggestion";
            const bodyNode = document.createElement("div");
            bodyNode.className = "assistant-response-body small";
            bodyNode.textContent = item;
            node.appendChild(titleNode);
            node.appendChild(bodyNode);
            assistantSuggestions.appendChild(node);
        });
    }

    function autoResizeAssistantPrompt() {
        if (!assistantPrompt) return;
        assistantPrompt.style.height = "auto";
        const nextHeight = Math.min(Math.max(assistantPrompt.scrollHeight, 34), 55);
        assistantPrompt.style.height = `${nextHeight}px`;
    }

    async function sendAssistantMessage(message = "") {
        const response = await fetch("/assistant/chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]")?.value || ""
            },
            body: JSON.stringify({ message, context: currentAssistantContext() })
        });
        if (!response.ok) {
            throw new Error("Assistant chat failed");
        }
        const payload = await response.json();
        if (payload?.context) {
            assistantMode = payload.context;
            window.sessionStorage.setItem("bayafya-assistant-mode", assistantMode);
            syncAssistantModeTabs();
        }
        renderAssistantHistory(payload.history || []);
        renderAssistantSuggestions(payload);
        return payload;
    }

    async function askAssistant(context, text = "", patientId = "") {
        const url = new URL("/assistant/suggest/", window.location.origin);
        url.searchParams.set("context", context || currentAssistantContext());
        if (text) url.searchParams.set("text", text);
        if (patientId) url.searchParams.set("patient_id", patientId);
        const response = await fetch(url.toString(), { headers: { "X-Requested-With": "XMLHttpRequest" } });
        if (!response.ok) {
            throw new Error("Assistant request failed");
        }
        const payload = await response.json();
        renderAssistantSuggestions(payload);
    }

    function ensureLeafletAssets() {
        if (window.L) {
            return Promise.resolve(window.L);
        }
        if (window.__bayhealthLeafletPromise) {
            return window.__bayhealthLeafletPromise;
        }
        window.__bayhealthLeafletPromise = new Promise((resolve, reject) => {
            if (!document.querySelector('link[data-leaflet]')) {
                const stylesheet = document.createElement("link");
                stylesheet.rel = "stylesheet";
                stylesheet.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
                stylesheet.dataset.leaflet = "1";
                document.head.appendChild(stylesheet);
            }
            const script = document.createElement("script");
            script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
            script.async = true;
            script.onload = () => resolve(window.L);
            script.onerror = reject;
            document.body.appendChild(script);
        });
        return window.__bayhealthLeafletPromise;
    }

    function riskToneClass(riskLevel) {
        if (riskLevel === "high") return "danger";
        if (riskLevel === "moderate") return "warning";
        return "success";
    }

    function createInfoChip(text, iconClass, toneClass = "") {
        const chip = document.createElement("span");
        chip.className = `info-chip${toneClass ? ` ${toneClass}` : ""}`;
        chip.innerHTML = `<i class="bi ${iconClass}"></i>${text}`;
        return chip;
    }

    function formatCareSettingLabel(value) {
        const labels = {
            home_monitoring: "Home monitoring",
            outpatient_review: "Outpatient review",
            same_day_clinic: "Same-day clinic",
            urgent_in_person: "Urgent in-person review",
            emergency_care: "Emergency care",
        };
        return labels[value] || "Outpatient review";
    }

    function renderSymptomAssessment(payload) {
        const section = document.getElementById("symptomResultSection");
        const disease = document.getElementById("symptomDisease");
        const summary = document.getElementById("symptomSummary");
        const confidence = document.getElementById("symptomConfidence");
        const guidance = document.getElementById("symptomGuidance");
        const riskBadge = document.getElementById("symptomRiskBadge");
        const timelineCopy = document.getElementById("symptomTimelineCopy");
        const redFlags = document.getElementById("symptomRedFlags");
        const redFlagsSection = document.getElementById("symptomRedFlagsSection");
        const nextSteps = document.getElementById("symptomNextSteps");
        const nextStepsSection = document.getElementById("symptomNextStepsSection");
        const careSetting = document.getElementById("symptomCareSetting");
        const clinicalRationale = document.getElementById("symptomClinicalRationale");
        const differentialSection = document.getElementById("symptomDifferentialSection");
        const differentialList = document.getElementById("symptomDifferentials");
        const evaluationSection = document.getElementById("symptomEvaluationSection");
        const evaluationList = document.getElementById("symptomEvaluation");
        const hospitalContext = document.getElementById("symptomHospitalContext");
        const hospitalContextText = document.getElementById("symptomHospitalContextText");
        const assistantCopy = document.getElementById("symptomAssistantCopy");
        if (!section || !payload || !payload.result) return;

        section.classList.remove("d-none");
        disease.textContent = payload.result.disease || "Structured symptom review";
        summary.textContent = payload.result.summary || "BayAfya Assistant generated a care-oriented assessment.";
        confidence.textContent = Number(payload.result.confidence || 0).toFixed(2);
        guidance.textContent = payload.result.guidance || "Arrange a professional review if symptoms persist or worsen.";
        riskBadge.className = `status-pill ${riskToneClass(payload.result.risk_level)}`;
        riskBadge.textContent = `${String(payload.result.risk_level || "low").charAt(0).toUpperCase()}${String(payload.result.risk_level || "low").slice(1)}`;
        if (clinicalRationale) {
            clinicalRationale.textContent = payload.result.clinical_rationale || "BayAfya will explain the reasoning for the assessment here.";
        }
        if (timelineCopy) {
            const parts = [];
            if (payload.structured_context?.onset_summary) parts.push(`Onset: ${payload.structured_context.onset_summary}.`);
            if (payload.structured_context?.progression) parts.push(`Progression: ${String(payload.structured_context.progression).charAt(0).toUpperCase()}${String(payload.structured_context.progression).slice(1)}.`);
            if (payload.structured_context?.intensity) parts.push(`Intensity: ${payload.structured_context.intensity}/10.`);
            timelineCopy.textContent = parts.join(" ") || "Structured onset, progression, and intensity context will appear here.";
        }
        if (careSetting) {
            careSetting.innerHTML = "";
            careSetting.appendChild(createInfoChip(formatCareSettingLabel(payload.result.care_setting), "bi-hospital"));
        }

        if (hospitalContext && hospitalContextText) {
            if (payload.active_hospital) {
                hospitalContext.hidden = false;
                hospitalContextText.textContent = `Assessment guidance is being framed for ${payload.active_hospital}.`;
            }
        }

        if (redFlags && redFlagsSection) {
            redFlags.innerHTML = "";
            const flags = payload.result.red_flags || [];
            redFlagsSection.classList.toggle("d-none", !flags.length);
            flags.forEach((flag) => redFlags.appendChild(createInfoChip(flag, "bi-exclamation-diamond", "info-chip-alert")));
        }

        if (differentialList && differentialSection) {
            differentialList.innerHTML = "";
            const items = payload.result.differential_diagnoses || [];
            differentialSection.classList.toggle("d-none", !items.length);
            items.forEach((item) => differentialList.appendChild(createInfoChip(item, "bi-diagram-3")));
        }

        if (evaluationList && evaluationSection) {
            evaluationList.innerHTML = "";
            const items = payload.result.recommended_evaluation || [];
            evaluationSection.classList.toggle("d-none", !items.length);
            items.forEach((item) => evaluationList.appendChild(createInfoChip(item, "bi-clipboard2-check")));
        }

        if (nextSteps && nextStepsSection) {
            nextSteps.innerHTML = "";
            const steps = payload.result.next_steps || [];
            nextStepsSection.classList.toggle("d-none", !steps.length);
            steps.forEach((step) => nextSteps.appendChild(createInfoChip(step, "bi-arrow-right-circle")));
        }

        if (assistantCopy) {
            assistantCopy.textContent = payload.result.summary || payload.result.guidance || "BayAfya has completed the structured symptom assessment.";
        }
    }

    function renderSymptomHistory(history) {
        const list = document.getElementById("symptomHistoryList");
        if (!list) return;
        list.innerHTML = "";
        if (!history || !history.length) {
            list.innerHTML = '<div class="soft-section p-3 text-secondary">No symptom reviews recorded yet.</div>';
            return;
        }
        history.forEach((item) => {
            const card = document.createElement("article");
            card.className = "soft-section p-3";
            card.innerHTML = `
                <div class="d-flex justify-content-between align-items-start gap-3 flex-wrap">
                    <div>
                        <div class="fw-semibold">${item.predicted_disease || "Structured symptom review"}</div>
                        <div class="text-secondary small">${item.guidance || ""}</div>
                    </div>
                    <span class="status-pill ${riskToneClass(item.risk_level)}">${String(item.risk_level || "low").charAt(0).toUpperCase()}${String(item.risk_level || "low").slice(1)}</span>
                </div>
                <div class="text-secondary small mt-2">${item.checked_at} · Confidence ${Number(item.confidence || 0).toFixed(2)}</div>
            `;
            list.appendChild(card);
        });
    }

    function bindSymptomCheckerForm() {
        const form = document.querySelector("[data-symptom-checker]");
        if (!form) return;
        const submitButton = document.getElementById("symptomCheckSubmit");
        const errorBox = document.getElementById("symptomFormError");
        const assistantCopy = document.getElementById("symptomAssistantCopy");
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            form.querySelectorAll("[data-field-error]").forEach((node) => {
                node.textContent = "";
                node.classList.add("d-none");
            });
            if (errorBox) {
                errorBox.textContent = "";
                errorBox.classList.add("d-none");
            }
            if (assistantCopy) {
                assistantCopy.textContent = "BayAfya is analyzing the submitted symptom pattern and clinical timeline now.";
            }
            withBusyButton(submitButton, "", async () => {
                try {
                    const response = await fetch(getFormActionUrl(form, window.location.pathname), {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]")?.value || "",
                        },
                        body: new FormData(form),
                    });
                    const payload = await response.json();
                    if (!response.ok || !payload.ok) {
                        const errors = payload.errors || {};
                        Object.entries(errors).forEach(([fieldName, fieldErrors]) => {
                            const fieldError = form.querySelector(`[data-field-error="${fieldName}"]`);
                            if (fieldError) {
                                fieldError.textContent = fieldErrors.join(" ");
                                fieldError.classList.remove("d-none");
                            }
                        });
                        if (errorBox && !Object.keys(errors).length) {
                            errorBox.textContent = "The symptom review could not be completed right now.";
                            errorBox.classList.remove("d-none");
                        }
                        if (assistantCopy) {
                            assistantCopy.textContent = "The structured review could not be completed. Please correct the form and try again.";
                        }
                        return;
                    }
                    renderSymptomAssessment(payload);
                    renderSymptomHistory(payload.history || []);
                    appendToast(platformName, "BayAfya Assistant has updated the triage assessment.", payload.result?.risk_level === "high" ? "warning" : "success");
                } catch (error) {
                    if (errorBox) {
                        errorBox.textContent = "The symptom review could not be completed right now.";
                        errorBox.classList.remove("d-none");
                    }
                    if (assistantCopy) {
                        assistantCopy.textContent = "The structured review could not be completed right now. Please try again shortly.";
                    }
                }
            });
        });
    }

    function initSidenavLinks() {
        const sidenav = document.getElementById("siteNav");
        if (!sidenav || !window.bootstrap) return;
        const offcanvas = bootstrap.Offcanvas.getOrCreateInstance(sidenav);
        sidenav.querySelectorAll("a.sidenav-link[href]").forEach((link) => {
            link.addEventListener("click", (event) => {
                const href = link.getAttribute("href");
                if (!href || href.startsWith("#")) return;
                event.preventDefault();
                let navigated = false;
                const go = () => {
                    if (navigated) return;
                    navigated = true;
                    window.location.href = href;
                };
                sidenav.addEventListener("hidden.bs.offcanvas", go, { once: true });
                offcanvas.hide();
                window.setTimeout(go, 220);
            });
        });
    }

    function enhanceAutocompleteSelect(select) {
        if (select.dataset.autocompleteEnhanced === "1") return;
        const wrapper = document.createElement("div");
        wrapper.className = "autocomplete-shell";
        const search = document.createElement("input");
        search.type = "text";
        search.className = "form-control autocomplete-search";
        search.placeholder = `Search ${select.dataset.autocomplete || "options"}...`;
        search.autocomplete = "off";
        const list = document.createElement("div");
        list.className = "entity-search-list d-none autocomplete-list";
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(search);
        wrapper.appendChild(select);
        wrapper.appendChild(list);
        select.classList.add("d-none");
        let activeIndex = -1;

        const optionItems = () =>
            Array.from(select.options)
                .filter((option) => option.value)
                .map((option) => ({
                    value: option.value,
                    label: option.textContent.trim(),
                    subtitle: option.dataset.meta || option.dataset.subtitle || "",
                }));

        const syncSearch = () => {
            const selectedOption = select.selectedOptions[0];
            search.value = selectedOption && selectedOption.value ? selectedOption.textContent.trim() : "";
        };

        const closeList = () => {
            list.classList.add("d-none");
            activeIndex = -1;
        };

        const renderList = (items) => {
            clearElement(list);
            if (!items.length) {
                closeList();
                return;
            }
            items.forEach((item, index) => {
                const row = document.createElement("button");
                row.type = "button";
                row.className = "entity-search-item";
                row.dataset.index = String(index);
                row.innerHTML = `<span class="fw-semibold">${item.label}</span><span class="small text-secondary">${item.subtitle || select.dataset.autocomplete || "Record"}</span>`;
                row.addEventListener("click", () => {
                    select.value = item.value;
                    select.dispatchEvent(new Event("change", { bubbles: true }));
                    syncSearch();
                    closeList();
                });
                list.appendChild(row);
            });
            list.classList.remove("d-none");
        };

        const runSearch = () => {
            const term = search.value.trim().toLowerCase();
            const items = optionItems().filter((item) => {
                if (!term) return true;
                return item.label.toLowerCase().includes(term) || item.subtitle.toLowerCase().includes(term);
            });
            renderList(items.slice(0, 12));
        };

        syncSearch();
        search.addEventListener("input", runSearch);
        search.addEventListener("focus", runSearch);
        search.addEventListener("keydown", (event) => {
            const rows = Array.from(list.querySelectorAll(".entity-search-item"));
            if (!rows.length) return;
            if (event.key === "ArrowDown") {
                event.preventDefault();
                activeIndex = Math.min(activeIndex + 1, rows.length - 1);
            } else if (event.key === "ArrowUp") {
                event.preventDefault();
                activeIndex = Math.max(activeIndex - 1, 0);
            } else if (event.key === "Enter" && activeIndex >= 0) {
                event.preventDefault();
                rows[activeIndex].click();
                return;
            } else if (event.key === "Escape") {
                closeList();
                return;
            } else {
                return;
            }
            rows.forEach((row, index) => row.classList.toggle("is-active", index === activeIndex));
        });
        search.addEventListener("change", syncSearch);
        select.addEventListener("change", syncSearch);
        document.addEventListener("click", (event) => {
            if (!wrapper.contains(event.target)) {
                closeList();
            }
        });
        select.dataset.autocompleteEnhanced = "1";
    }

    function initShiftAssignmentStaffPicker(root = document) {
        root.querySelectorAll("form[data-shift-staff-url]").forEach((form) => {
            if (form.dataset.shiftStaffBound === "1") return;
            const url = form.dataset.shiftStaffUrl;
            const staffSelect = form.querySelector('select[name="staff"][data-shift-staff-select]');
            const startAt = form.querySelector('input[name="start_at"]');
            const endAt = form.querySelector('input[name="end_at"]');
            if (!url || !staffSelect || !startAt) return;

            const wrapper = staffSelect.closest(".autocomplete-shell");
            const searchInput = wrapper?.querySelector(".autocomplete-search");
            let requestToken = 0;

            const syncEligibleStaff = async () => {
                const token = ++requestToken;
                const params = new URLSearchParams();
                if (startAt.value) params.set("start_at", startAt.value);
                if (endAt?.value) params.set("end_at", endAt.value);
                if (searchInput?.value?.trim()) params.set("q", searchInput.value.trim());

                try {
                    const response = await fetch(`${url}?${params.toString()}`, {
                        headers: { "X-Requested-With": "XMLHttpRequest" },
                        credentials: "same-origin",
                    });
                    if (!response.ok || token !== requestToken) return;
                    const payload = await response.json();
                    const items = Array.isArray(payload.results) ? payload.results : [];
                    const currentValue = String(staffSelect.value || "");

                    staffSelect.innerHTML = "";
                    const placeholder = document.createElement("option");
                    placeholder.value = "";
                    placeholder.textContent = items.length
                        ? "Select eligible staff"
                        : "No eligible staff available for this shift window";
                    staffSelect.appendChild(placeholder);

                    items.forEach((item) => {
                        const option = document.createElement("option");
                        option.value = item.value;
                        option.textContent = item.full_label || item.label;
                        option.dataset.subtitle = item.subtitle || "";
                        if (String(item.value) === currentValue) {
                            option.selected = true;
                        }
                        staffSelect.appendChild(option);
                    });

                    if (!items.some((item) => String(item.value) === currentValue)) {
                        staffSelect.value = "";
                    }
                    staffSelect.disabled = !items.length;
                    staffSelect.dispatchEvent(new Event("change", { bubbles: true }));
                    if (searchInput?.value?.trim()) {
                        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
                    }
                } catch (_) {
                    return;
                }
            };

            const scheduleSync = () => {
                window.clearTimeout(form._shiftStaffTimer);
                form._shiftStaffTimer = window.setTimeout(syncEligibleStaff, 140);
            };

            [startAt, endAt].forEach((field) => {
                field?.addEventListener("change", scheduleSync);
                field?.addEventListener("input", scheduleSync);
            });
            searchInput?.addEventListener("input", scheduleSync);
            form.dataset.shiftStaffBound = "1";
            syncEligibleStaff();
        });
    }

    function initCopyCodeButtons(root = document) {
        root.querySelectorAll("[data-copy-code]").forEach((button) => {
            if (button.dataset.copyCodeBound === "1") return;
            button.dataset.copyCodeBound = "1";
            button.addEventListener("click", async () => {
                const value = button.dataset.copyCode || "";
                if (!value) return;
                try {
                    await navigator.clipboard.writeText(value);
                    appendToast(button.dataset.copyLabel || "Code", `${value} copied to clipboard.`, "success");
                } catch (_) {
                    appendToast(button.dataset.copyLabel || "Code", "Clipboard access is unavailable on this device.", "warning");
                }
            });
        });
    }

    function buildMetricSpotlightCards(container) {
        const entries = [];
        const candidates = Array.from(container.children || []);
        candidates.forEach((child, index) => {
            const card = child.matches(".metric-card") ? child : child.querySelector(".metric-card");
            if (!card) return;
            const link = child.matches("a[href]") ? child : child.querySelector("a.metric-link[href], a[href]");
            const labelNode = card.querySelector(".metric-label") || card.querySelector(".text-uppercase") || card.querySelector(".text-secondary.small");
            const valueNode = card.querySelector("[data-live-metric]") || card.querySelector(".metric-value") || card.querySelector(".display-6");
            const iconNode = card.querySelector(".metric-icon i");
            entries.push({
                id: `metric-${index}`,
                label: labelNode?.textContent?.trim() || `Metric ${index + 1}`,
                value: valueNode?.textContent?.trim() || "0",
                metric: valueNode?.dataset?.liveMetric || "",
                icon: iconNode?.className || "bi bi-bar-chart",
                href: link?.getAttribute("href") || "",
            });
        });
        return entries;
    }

    function renderMetricSpotlight(entry, active = false) {
        const tag = entry.href ? "a" : "button";
        const attrs = entry.href
            ? `href="${escapeHtml(entry.href)}"`
            : `type="button"`;
        return `
            <${tag} class="metric-spotlight-pill ${active ? "is-active" : ""}" ${attrs} data-metric-spotlight-pill data-spotlight-id="${escapeHtml(entry.id)}">
                <span class="metric-spotlight-pill-icon"><i class="${escapeHtml(entry.icon)}"></i></span>
                <span class="metric-spotlight-pill-copy">
                    <span class="metric-spotlight-pill-label">${escapeHtml(entry.label)}</span>
                    <span class="metric-spotlight-pill-value" ${entry.metric ? `data-live-metric="${escapeHtml(entry.metric)}"` : ""}>${escapeHtml(entry.value)}</span>
                </span>
            </${tag}>
        `;
    }

    function initMetricSpotlights(root = document) {
        const containers = root.querySelectorAll(".dashboard-grid.d-none.d-md-grid, .row.d-none.d-md-flex");
        containers.forEach((container) => {
            if (container.dataset.metricSpotlightBound === "1") return;
            const entries = buildMetricSpotlightCards(container);
            if (entries.length < 3) return;
            container.dataset.metricSpotlightBound = "1";
            container.classList.add("metric-spotlight-source");

            const shell = document.createElement("section");
            shell.className = "metric-spotlight d-none d-md-grid";
            shell.innerHTML = `
                <div class="metric-spotlight-main" data-metric-spotlight-main></div>
                <div class="metric-spotlight-rail" data-metric-spotlight-rail></div>
            `;

            const main = shell.querySelector("[data-metric-spotlight-main]");
            const rail = shell.querySelector("[data-metric-spotlight-rail]");
            let activeIndex = 0;

            const paint = () => {
                const active = entries[activeIndex];
                const mainTag = active.href ? "a" : "div";
                const mainAttrs = active.href ? `href="${escapeHtml(active.href)}"` : "";
                main.innerHTML = `
                    <${mainTag} class="metric-spotlight-card" ${mainAttrs}>
                        <div class="metric-spotlight-card-icon"><i class="${escapeHtml(active.icon)}"></i></div>
                        <div class="metric-spotlight-card-copy">
                            <div class="metric-spotlight-card-label">${escapeHtml(active.label)}</div>
                            <div class="metric-spotlight-card-value" ${active.metric ? `data-live-metric="${escapeHtml(active.metric)}"` : ""}>${escapeHtml(active.value)}</div>
                            <div class="metric-spotlight-card-note">Tap another metric pill to refocus this panel.</div>
                        </div>
                    </${mainTag}>
                `;
                rail.innerHTML = entries.map((entry, index) => renderMetricSpotlight(entry, index === activeIndex)).join("");
                rail.querySelectorAll("[data-metric-spotlight-pill]").forEach((pill, index) => {
                    if (entries[index].href) return;
                    pill.addEventListener("click", () => {
                        activeIndex = index;
                        paint();
                    });
                });
            };

            container.insertAdjacentElement("afterend", shell);
            paint();
        });
    }

    function enhanceEntitySearchInput(input) {
        if (input.dataset.entitySearchEnhanced === "1") return;
        const wrapper = document.createElement("div");
        wrapper.className = "entity-search-shell";
        const list = document.createElement("div");
        list.className = "entity-search-list d-none";
        const entityType = input.dataset.entitySearch || "patient";
        let requestToken = 0;

        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
        wrapper.appendChild(list);

        const render = (items) => {
            clearElement(list);
            if (!items.length) {
                list.classList.add("d-none");
                return;
            }
            items.forEach((item) => {
                const row = document.createElement("button");
                row.type = "button";
                row.className = "entity-search-item";
                row.innerHTML = `<span class="fw-semibold">${item.label}</span><span class="small text-secondary">${item.subtitle || item.kind || ""}</span>`;
                row.addEventListener("click", () => {
                    input.value = item.value || item.label;
                    list.classList.add("d-none");
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                });
                list.appendChild(row);
            });
            list.classList.remove("d-none");
        };

        const search = debounce(async () => {
            const term = input.value.trim();
            if (term.length < 2) {
                list.classList.add("d-none");
                return;
            }
            const current = ++requestToken;
            try {
                const response = await fetch(`/search/suggestions/?type=${encodeURIComponent(entityType)}&q=${encodeURIComponent(term)}`, {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                if (!response.ok || current !== requestToken) return;
                const payload = await response.json();
                render(payload.results || []);
            } catch (error) {
                list.classList.add("d-none");
            }
        }, 260);

        input.addEventListener("input", search);
        input.addEventListener("focus", search);
        document.addEventListener("click", (event) => {
            if (!wrapper.contains(event.target)) {
                list.classList.add("d-none");
            }
        });
        input.dataset.entitySearchEnhanced = "1";
    }

    function bindAssistantLiveFields() {
        document.querySelectorAll("[data-assistant-live]").forEach((field) => {
            const output = document.querySelector(field.dataset.assistantTarget);
            const context = field.dataset.assistantLive;
            if (!output) return;
            const run = debounce(async () => {
                output.innerHTML = '<div class="text-white-50 small">Loading suggestions...</div>';
                try {
                    const response = await fetch(`/assistant/suggest/?context=${encodeURIComponent(context)}&text=${encodeURIComponent(field.value || "")}`, {
                        headers: { "X-Requested-With": "XMLHttpRequest" }
                    });
                    const payload = await response.json();
                    const suggestions = payload.suggestions || [];
                    output.innerHTML = "";
                    if (!suggestions.length) {
                        output.innerHTML = '<div class="assistant-response-card small text-secondary">Suggestions will appear as you type.</div>';
                        return;
                    }
                    suggestions.forEach((item) => {
                        const card = document.createElement("div");
                        card.className = "assistant-response-card";
                        const titleNode = document.createElement("div");
                        titleNode.className = "assistant-response-title mb-1";
                        titleNode.textContent = payload.title || "Suggestion";
                        const bodyNode = document.createElement("div");
                        bodyNode.className = "assistant-response-body small";
                        bodyNode.textContent = item;
                        card.appendChild(titleNode);
                        card.appendChild(bodyNode);
                        output.appendChild(card);
                    });
                } catch (error) {
                    output.innerHTML = '<div class="assistant-response-card small text-secondary">Assistant suggestions are temporarily unavailable.</div>';
                }
            }, 350);
            field.addEventListener("input", run);
            field.addEventListener("focus", run);
            if (field.value) {
                run();
            }
        });
    }

    function bindAutoGeneratedHospitalCode() {
        document.querySelectorAll("[data-auto-slug-target]").forEach((source) => {
            if (source.dataset.slugBound === "1") return;
            const target = document.querySelector(source.dataset.autoSlugTarget);
            if (!target) return;
            const sync = () => {
                target.value = slugifyCode(source.value);
            };
            source.addEventListener("input", sync);
            source.addEventListener("change", sync);
            sync();
            source.dataset.slugBound = "1";
        });
    }

    function bindRegisterWizard() {
        const form = document.querySelector("[data-register-wizard]");
        if (!form) return;

        const steps = Array.from(form.querySelectorAll("[data-step-index]"));
        const previousButton = form.querySelector("[data-register-prev]");
        const nextButton = form.querySelector("[data-register-next]");
        const submitButton = form.querySelector("[data-register-submit]");
        const progress = form.querySelector("[data-register-progress]");
        const stepLabel = form.querySelector("[data-register-step-label]");
        const roleField = form.querySelector("#id_role");
        const dateField = form.querySelector("#id_date_of_birth");
        const passwordField = form.querySelector("#id_password");
        const confirmPasswordField = form.querySelector("#id_confirm_password");
        const passwordMeter = form.querySelector("[data-password-meter]");
        const passwordMeterLabel = form.querySelector("[data-password-meter-label]");
        const passwordMatchLabel = form.querySelector("[data-password-match-label]");
        const adminOnlySection = form.querySelector("[data-admin-only-section]");
        let currentStep = Math.max(0, steps.findIndex((step) => step.classList.contains("is-active")));
        if (currentStep < 0) currentStep = 0;

        const setDateBounds = () => {
            if (!dateField) return;
            const today = new Date();
            const yyyy = today.getFullYear();
            const mm = String(today.getMonth() + 1).padStart(2, "0");
            const dd = String(today.getDate()).padStart(2, "0");
            const todayIso = `${yyyy}-${mm}-${dd}`;
            const adultCutoff = new Date(today);
            adultCutoff.setFullYear(adultCutoff.getFullYear() - 18);
            const adultIso = `${adultCutoff.getFullYear()}-${String(adultCutoff.getMonth() + 1).padStart(2, "0")}-${String(adultCutoff.getDate()).padStart(2, "0")}`;
            const staffRoles = new Set(["doctor", "nurse", "receptionist", "lab_technician", "pharmacist", "counselor", "emergency_operator"]);
            if (roleField && staffRoles.has(roleField.value)) {
                dateField.max = adultIso;
            } else {
                dateField.max = todayIso;
            }
            const minDate = new Date(today);
            minDate.setFullYear(minDate.getFullYear() - 120);
            dateField.min = `${minDate.getFullYear()}-${String(minDate.getMonth() + 1).padStart(2, "0")}-${String(minDate.getDate()).padStart(2, "0")}`;
        };

        const passwordScore = (value) => {
            let score = 0;
            if (!value) return score;
            if (value.length >= 8) score += 1;
            if (value.length >= 12) score += 1;
            if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1;
            if (/\d/.test(value)) score += 1;
            if (/[^A-Za-z0-9]/.test(value)) score += 1;
            if (value.length >= 16 && /[^A-Za-z0-9]/.test(value)) score += 1;
            return Math.min(score, 5);
        };

        const passwordTier = (score) => {
            if (score <= 1) return { label: "Weak", tone: "danger", width: "20%" };
            if (score === 2) return { label: "Fair", tone: "warning", width: "40%" };
            if (score === 3) return { label: "Strong", tone: "info", width: "65%" };
            if (score === 4) return { label: "Very strong", tone: "success", width: "82%" };
            return { label: "Extra strong", tone: "success", width: "100%" };
        };

        const syncPasswordState = () => {
            if (!passwordField) return;
            const score = passwordScore(passwordField.value || "");
            const tier = passwordTier(score);
            if (passwordMeter) {
                passwordMeter.style.width = tier.width;
                passwordMeter.dataset.tone = tier.tone;
            }
            if (passwordMeterLabel) {
                passwordMeterLabel.textContent = passwordField.value ? `Password strength: ${tier.label}` : "Password strength: waiting";
            }
            if (confirmPasswordField && passwordMatchLabel) {
                if (!confirmPasswordField.value && !passwordField.value) {
                    passwordMatchLabel.textContent = "Confirm password to continue.";
                    passwordMatchLabel.className = "bh-field-help";
                } else if (confirmPasswordField.value === passwordField.value) {
                    passwordMatchLabel.textContent = "Passwords match.";
                    passwordMatchLabel.className = "bh-field-help text-success";
                } else {
                    passwordMatchLabel.textContent = "Passwords do not match.";
                    passwordMatchLabel.className = "bh-field-error d-inline-flex";
                }
            }
        };

        const activeSteps = () => {
            if (roleField && roleField.value === "admin") {
                return steps;
            }
            return steps.filter((step) => step.dataset.stepIndex !== "4");
        };

        const stepFields = (step) =>
            Array.from(step.querySelectorAll("input, select, textarea")).filter((field) => {
                if (field.disabled || field.type === "hidden") return false;
                if (field.closest(".d-none")) return false;
                return true;
            });

        const validateStep = (step) => {
            const fields = stepFields(step);
            for (const field of fields) {
                if (field.required && !field.value) {
                    field.reportValidity();
                    return false;
                }
                if (field.type === "email" && field.value && !field.checkValidity()) {
                    field.reportValidity();
                    return false;
                }
            }
            return true;
        };

        const syncAdminSection = () => {
            if (!adminOnlySection || !roleField) return;
            const isAdmin = roleField.value === "admin";
            adminOnlySection.classList.toggle("d-none", !isAdmin);
            adminOnlySection.querySelectorAll("input, textarea, select").forEach((field) => {
                field.disabled = !isAdmin;
            });
        };

        const render = () => {
            syncAdminSection();
            setDateBounds();
            const visibleSteps = activeSteps();
            currentStep = Math.min(currentStep, visibleSteps.length - 1);
            steps.forEach((step) => step.classList.remove("is-active"));
            visibleSteps[currentStep].classList.add("is-active");
            if (progress) {
                progress.style.width = `${((currentStep + 1) / visibleSteps.length) * 100}%`;
            }
            if (stepLabel) {
                stepLabel.textContent = `Step ${currentStep + 1} of ${visibleSteps.length}`;
            }
            if (previousButton) previousButton.disabled = currentStep === 0;
            if (nextButton) nextButton.classList.toggle("d-none", currentStep === visibleSteps.length - 1);
            if (submitButton) submitButton.classList.toggle("d-none", currentStep !== visibleSteps.length - 1);
        };

        if (previousButton) {
            previousButton.addEventListener("click", () => {
                currentStep = Math.max(0, currentStep - 1);
                render();
            });
        }

        if (nextButton) {
            nextButton.addEventListener("click", () => {
                const visibleSteps = activeSteps();
                const step = visibleSteps[currentStep];
                if (!validateStep(step)) return;
                currentStep = Math.min(currentStep + 1, visibleSteps.length - 1);
                render();
            });
        }

        if (roleField) {
            roleField.addEventListener("change", () => {
                render();
            });
        }

        [passwordField, confirmPasswordField].forEach((field) => {
            if (field) {
                field.addEventListener("input", syncPasswordState);
                field.addEventListener("blur", syncPasswordState);
            }
        });

        render();
        syncPasswordState();
    }

    function enhanceLocationPicker(field) {
        if (field.dataset.locationEnhanced === "1") return;
        const DEFAULT_NAIROBI = { latitude: -1.286389, longitude: 36.817223, label: "Nairobi, Kenya" };
        const wrapper = document.createElement("div");
        wrapper.className = "location-picker-shell";
        if (field.dataset.locationHideMap === "1") {
            wrapper.classList.add("location-picker-hidden-map");
        }
        const toolbar = document.createElement("div");
        toolbar.className = "location-picker-toolbar";
        const search = document.createElement("input");
        search.type = "search";
        search.className = "form-control";
        search.placeholder = `Search ${field.dataset.locationLabel || "location"} with map support`;
        const useCurrent = document.createElement("button");
        useCurrent.type = "button";
        useCurrent.className = "bh-btn bh-btn-surface bh-btn-inline";
        useCurrent.innerHTML = '<i class="bi bi-crosshair"></i><span>Use current location</span>';
        const suggestions = document.createElement("div");
        suggestions.className = "entity-search-list d-none location-suggestion-list";
        const mapNode = document.createElement("div");
        mapNode.className = "location-picker-map";

        field.parentNode.insertBefore(wrapper, field);
        wrapper.appendChild(toolbar);
        toolbar.appendChild(search);
        toolbar.appendChild(useCurrent);
        wrapper.appendChild(suggestions);
        wrapper.appendChild(field);
        wrapper.appendChild(mapNode);

        let map = null;
        let marker = null;

        const renderMap = async (latitude, longitude, label = "") => {
            try {
                await ensureLeafletAssets();
                if (!map) {
                    map = window.L.map(mapNode, { zoomControl: true }).setView([latitude, longitude], 14);
                    window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                        maxZoom: 19,
                        attribution: "&copy; OpenStreetMap contributors"
                    }).addTo(map);
                } else {
                    map.setView([latitude, longitude], 14);
                }
                if (!marker) {
                    marker = window.L.marker([latitude, longitude]).addTo(map);
                } else {
                    marker.setLatLng([latitude, longitude]);
                }
                if (label) {
                    marker.bindPopup(label).openPopup();
                }
                window.setTimeout(() => map.invalidateSize(), 120);
            } catch (error) {
                mapNode.classList.add("d-none");
            }
        };

        const renderDefaultMap = () => {
            if (field.dataset.locationHideMap === "1") {
                mapNode.classList.add("d-none");
            }
            renderMap(DEFAULT_NAIROBI.latitude, DEFAULT_NAIROBI.longitude, DEFAULT_NAIROBI.label);
        };

        const closeSuggestions = () => suggestions.classList.add("d-none");

        const renderSuggestions = (results) => {
            clearElement(suggestions);
            if (!results.length) {
                closeSuggestions();
                return;
            }
            results.forEach((item) => {
                const row = document.createElement("button");
                row.type = "button";
                row.className = "entity-search-item";
                row.innerHTML = `<span class="fw-semibold">${item.display_name}</span><span class="small text-secondary">${item.type || "Location"}</span>`;
                row.addEventListener("click", () => {
                    field.value = item.display_name;
                    search.value = item.display_name;
                    closeSuggestions();
                    renderMap(Number(item.lat), Number(item.lon), item.display_name);
                });
                suggestions.appendChild(row);
            });
            suggestions.classList.remove("d-none");
        };

        const searchLocations = debounce(async () => {
            const term = search.value.trim();
            if (term.length < 3) {
                closeSuggestions();
                return;
            }
            try {
                const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&q=${encodeURIComponent(term)}`);
                if (!response.ok) {
                    closeSuggestions();
                    return;
                }
                const results = await response.json();
                renderSuggestions(results);
            } catch (error) {
                closeSuggestions();
            }
        }, 300);

        search.addEventListener("input", searchLocations);
        search.addEventListener("focus", searchLocations);
        useCurrent.addEventListener("click", () => {
            if (!navigator.geolocation) {
                appendToast("Location unavailable", "This browser cannot access device location.", "warning");
                return;
            }
            navigator.geolocation.getCurrentPosition(
                async (position) => {
                    const latitude = position.coords.latitude;
                    const longitude = position.coords.longitude;
                    try {
                        const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`);
                        const payload = await response.json();
                        const label = payload.display_name || `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
                        field.value = label;
                        search.value = label;
                        renderMap(latitude, longitude, label);
                    } catch (error) {
                        const fallback = `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;
                        field.value = fallback;
                        search.value = fallback;
                        renderMap(latitude, longitude, fallback);
                    }
                },
                () => appendToast("Location unavailable", "Device location could not be retrieved right now.", "warning"),
                { enableHighAccuracy: true, timeout: 10000 }
            );
        });
        document.addEventListener("click", (event) => {
            if (!wrapper.contains(event.target)) {
                closeSuggestions();
            }
        });
        if (field.value.trim()) {
            search.value = field.value.trim();
        } else if (field.dataset.locationDefault) {
            const defaultLabel = field.dataset.locationDefault || DEFAULT_NAIROBI.label;
            search.value = defaultLabel;
            renderMap(DEFAULT_NAIROBI.latitude, DEFAULT_NAIROBI.longitude, defaultLabel);
        } else {
            renderDefaultMap();
        }
        field.dataset.locationEnhanced = "1";
    }

    function updateAssistantFabVisibility(show) {
        if (!assistantFab) return;
        if (document.body.classList.contains("assistant-panel-open") || (assistantPanel && assistantPanel.classList.contains("show"))) {
            assistantFab.classList.remove("is-visible");
            assistantFab.hidden = true;
            return;
        }
        const shouldShow = typeof show === "boolean" ? show : (window.scrollY || 0) > 80;
        assistantFab.hidden = !shouldShow;
        assistantFab.classList.toggle("is-visible", shouldShow);
    }

    function enhanceScrollableLists() {
        document.querySelectorAll(".stacked-list, .list-soft, [data-scroll-cards]").forEach((container) => {
            const visibleChildren = Array.from(container.children).filter((child) => !child.hidden);
            container.classList.toggle("has-scroll-window", visibleChildren.length > 5);
        });
    }

    function bindWalkInExistingPatientPrefill() {
        const select = document.getElementById("id_existing_patient");
        const preview = document.getElementById("walkInExistingPatientPreviewText");
        const payloadNode = document.getElementById("walkInPatientLookup");
        if (!select || !payloadNode) return;
        let lookup = {};
        try {
            lookup = JSON.parse(payloadNode.textContent || "{}");
        } catch (error) {
            lookup = {};
        }
        const fieldMap = {
            first_name: document.getElementById("id_first_name"),
            last_name: document.getElementById("id_last_name"),
            email: document.getElementById("id_email"),
            phone: document.getElementById("id_phone"),
            date_of_birth: document.getElementById("id_date_of_birth"),
            gender: document.getElementById("id_gender"),
        };
        const update = () => {
            const details = lookup[String(select.value || "")];
            if (!details) {
                if (preview) {
                    preview.textContent = "Select an existing patient and their core profile details will be carried into the intake form automatically.";
                }
                return;
            }
            Object.entries(fieldMap).forEach(([key, field]) => {
                if (!field) return;
                field.value = details[key] || "";
            });
            if (preview) {
                preview.textContent = `${details.patient_number || "Existing patient"} · ${details.age_group || "Unknown age group"} · ${details.insurance || "No insurance recorded"}${details.history ? ` · ${details.history}` : ""}`;
            }
        };
        select.addEventListener("change", update);
        update();
    }

    document.querySelectorAll("select[data-autocomplete]").forEach(enhanceAutocompleteSelect);
    initMetricSpotlights();
    initShiftAssignmentStaffPicker();
    document.querySelectorAll("input[data-entity-search]").forEach(enhanceEntitySearchInput);
    document.querySelectorAll("[data-location-picker]").forEach(enhanceLocationPicker);
    bindAutoGeneratedHospitalCode();
    bindRegisterWizard();
    bindStandalonePasswordMeters();
    initPasswordVisibilityToggles();
    bindAuthActionButtons();
    initEmailVerificationFlow();
    bindAssistantLiveFields();
    bindSymptomCheckerForm();
    bindWalkInExistingPatientPrefill();
    enhanceScrollableLists();
    applySmartFillRows();
    initCopyCodeButtons();
    initAdmissionDependentSelectors();
    initRotatingCardStacks();
    updateAssistantFabVisibility(false);
    assistantMode = defaultAssistantMode();
    syncAssistantModeTabs();

    if (assistantAskButton && assistantPrompt && assistantPanel) {
        const populateDefault = async () => {
            renderAssistantHistoryLoader();
            try {
                const payload = await sendAssistantMessage("");
                if (assistantChatStream) {
                    assistantChatStream.dataset.initialized = "1";
                    window.requestAnimationFrame(() => {
                        assistantChatStream.scrollTop = assistantChatStream.scrollHeight;
                    });
                }
                const hasUserTurn = (payload?.history || []).some((entry) => entry.role === "user");
                setAssistantChatCompactMode(hasUserTurn);
                autoResizeAssistantPrompt();
            } catch (error) {
                if (assistantSummary) assistantSummary.textContent = "Assistant suggestions are temporarily unavailable.";
            }
        };
        assistantPanel.addEventListener("show.bs.offcanvas", () => {
            document.body.classList.add("assistant-panel-open");
            updateAssistantFabVisibility(false);
            scrollAssistantWorkspaceTo(0);
        });
        assistantPanel.addEventListener("shown.bs.offcanvas", populateDefault);
        assistantPanel.addEventListener("shown.bs.offcanvas", () => {
            autoResizeAssistantPrompt();
            assistantPrompt.focus();
        });
        assistantPanel.addEventListener("hidden.bs.offcanvas", () => {
            document.body.classList.remove("assistant-panel-open");
            setAssistantChatCompactMode(false);
            updateAssistantFabVisibility((window.scrollY || 0) > 80);
        });
        assistantAskButton.addEventListener("click", async () => {
            const message = (assistantPrompt.value || "").trim();
            if (!message) {
                assistantPrompt.focus();
                return;
            }
            assistantPrompt.value = "";
            autoResizeAssistantPrompt();
            setAssistantChatCompactMode(true);
            appendAssistantMessage("user", message);
            assistantAskButton.disabled = true;
            const original = assistantAskButton.innerHTML;
            const loadingBubble = appendAssistantLoadingBubble();
            assistantAskButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`;
            try {
                await sendAssistantMessage(message);
            } catch (error) {
                if (assistantSummary) assistantSummary.textContent = "Assistant suggestions are temporarily unavailable.";
            } finally {
                loadingBubble?.remove();
                assistantAskButton.disabled = false;
                assistantAskButton.innerHTML = original;
            }
        });
        assistantPrompt.addEventListener("keydown", async (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                assistantAskButton.click();
            }
        });
        assistantPrompt.addEventListener("input", autoResizeAssistantPrompt);
        if (assistantChatStream) {
            assistantChatStream.addEventListener("scroll", debounce(() => {
                setAssistantChatCompactMode((assistantChatStream.scrollTop || 0) > 8);
            }, 20));
        }
        if (assistantClearButton) {
            assistantClearButton.addEventListener("click", async () => {
                try {
                    await fetch("/assistant/chat/clear/", {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                            "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]")?.value || "",
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({ context: currentAssistantContext() })
                    });
                    renderAssistantHistory([]);
                    if (assistantChatStream) {
                        assistantChatStream.dataset.initialized = "1";
                    }
                    if (assistantPrompt) {
                        assistantPrompt.value = "";
                        autoResizeAssistantPrompt();
                    }
                    renderAssistantSuggestions({
                        summary: "Start a new conversation in the current workspace.",
                        safety: "Assistant guidance should still be interpreted with the appropriate clinical or operational judgment.",
                        suggestions: [],
                    });
                } catch (error) {
                    if (assistantSummary) assistantSummary.textContent = "Assistant suggestions are temporarily unavailable.";
                }
            });
        }
        if (assistantModeBar) {
            assistantModeBar.addEventListener("wheel", (event) => {
                if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
                    assistantModeBar.scrollLeft += event.deltaY;
                    event.preventDefault();
                }
            }, { passive: false });
            assistantModeBar.querySelectorAll("[data-assistant-mode]").forEach((tab) => {
                tab.addEventListener("click", async () => {
                    assistantMode = tab.dataset.assistantMode || "general";
                    window.sessionStorage.setItem("bayafya-assistant-mode", assistantMode);
                    syncAssistantModeTabs();
                    tab.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
                    if (assistantPrompt) {
                        assistantPrompt.value = "";
                        autoResizeAssistantPrompt();
                    }
                    if (assistantChatStream) {
                        assistantChatStream.dataset.initialized = "0";
                    }
                    renderAssistantHistoryLoader();
                    try {
                        await sendAssistantMessage("");
                    } catch (error) {
                        if (assistantSummary) assistantSummary.textContent = "Assistant suggestions are temporarily unavailable.";
                    }
                });
            });
        }
        if (assistantWorkspaceDots) {
            assistantWorkspaceDots.querySelectorAll("[data-assistant-dot]").forEach((dot) => {
                dot.addEventListener("click", () => {
                    scrollAssistantWorkspaceTo(Number(dot.dataset.assistantDot || 0));
                });
            });
        }
        if (assistantWorkspaceRail) {
            assistantWorkspaceRail.addEventListener("scroll", debounce(() => {
                const width = assistantWorkspaceRail.clientWidth || 1;
                const index = Math.round(assistantWorkspaceRail.scrollLeft / width);
                syncAssistantWorkspaceDots(index);
            }, 40));
            assistantWorkspaceRail.addEventListener("wheel", (event) => {
                if (event.target?.closest?.(".assistant-chat-stream, .assistant-drawer-stack-insights, .assistant-prompt-field")) {
                    return;
                }
                if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
                    assistantWorkspaceRail.scrollLeft += event.deltaY;
                    event.preventDefault();
                }
            }, { passive: false });
        }
    }

    document.querySelectorAll("[data-message-toast]").forEach((node) => {
        appendToast(node.dataset.messageTitle || platformName, node.dataset.messageToast, node.dataset.messageTone || "primary");
    });

    document.querySelectorAll("[data-auto-show-modal]").forEach((node) => {
        if (!window.bootstrap) return;
        const modal = new bootstrap.Modal(node, { backdrop: "static" });
        window.setTimeout(() => modal.show(), 250);
    });

    document.querySelectorAll("[data-modal-launch]").forEach((trigger) => {
        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            const targetId = trigger.dataset.modalLaunch;
            const target = targetId ? document.getElementById(targetId) : null;
            if (!target || !window.bootstrap) return;
            const modal = bootstrap.Modal.getOrCreateInstance(target);
            modal.show();
        });
    });

    window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault();
        deferredInstallPrompt = event;
        showPwaBanner();
    });

    window.addEventListener("appinstalled", () => {
        deferredInstallPrompt = null;
        hidePwaBanner();
        sessionStorage.setItem("baycare-pwa-dismissed", "1");
        appendToast(platformName, `${platformName} is now available from your device home screen.`, "success");
    });

    if (pwaInstallTrigger) {
        pwaInstallTrigger.addEventListener("click", async () => {
            if (!deferredInstallPrompt) {
                appendToast("Install unavailable", "The browser has not exposed an install prompt yet.", "warning");
                return;
            }
            deferredInstallPrompt.prompt();
            const choice = await deferredInstallPrompt.userChoice;
            if (choice.outcome === "accepted") {
                appendToast(platformName, `Follow the device prompt to finish adding ${platformName}.`, "success");
            } else {
                appendToast(platformName, `You can install ${platformName} later from the browser menu.`, "info");
            }
            deferredInstallPrompt = null;
            hidePwaBanner();
            sessionStorage.setItem("baycare-pwa-dismissed", "1");
        });
    }

    if (pwaDismissTrigger) {
        pwaDismissTrigger.addEventListener("click", () => {
            hidePwaBanner();
            sessionStorage.setItem("baycare-pwa-dismissed", "1");
        });
    }

    if ("serviceWorker" in navigator && !isStandaloneDisplay()) {
        window.addEventListener("load", () => {
            navigator.serviceWorker.register("/service-worker.js").catch(() => {
                appendToast("Offline support unavailable", "The service worker could not be registered right now.", "warning");
            });
        });
    }

    if (isStandaloneDisplay()) {
        hidePwaBanner();
    } else {
        showPwaBanner();
    }

    const assistantScrollHandler = () => {
        if (!assistantFab) return;
        updateAssistantFabVisibility(false);
        lastScrollPosition = window.scrollY || 0;
        window.clearTimeout(assistantScrollIdleTimer);
        assistantScrollIdleTimer = window.setTimeout(() => {
            updateAssistantFabVisibility((window.scrollY || 0) > 80);
        }, 320);
    };

    window.addEventListener("scroll", assistantScrollHandler, { passive: true });
    window.addEventListener("resize", debounce(() => {
        updateAssistantFabVisibility((window.scrollY || 0) > 80);
        applySmartFillRows();
    }, 80));

    const notificationSocketMeta = document.getElementById("notificationSocketMeta");
    if (notificationSocketMeta) {
        let latestNotificationId = 0;
        let initializedNotificationPoll = false;
        let notificationSocket = null;
        const pollNotifications = async () => {
            try {
                const response = await fetch(`/notifications/feed/?since_id=${latestNotificationId}`, {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                });
                if (!response.ok) return;
                const payload = await response.json();
                if (!initializedNotificationPoll) {
                    latestNotificationId = payload.latest_id || latestNotificationId;
                    initializedNotificationPoll = true;
                    return;
                }
                (payload.items || []).forEach((item) => {
                    latestNotificationId = Math.max(latestNotificationId, Number(item.id) || latestNotificationId);
                    appendToast(item.title || "Notification", item.message || "New update received.", "info");
                });
            } catch (_) {
                return;
            }
        };
        const startNotificationPolling = () => {
            pollNotifications();
            window.setInterval(() => {
                if (document.hidden) return;
                pollNotifications();
            }, 15000);
        };
        const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
        try {
            notificationSocket = new WebSocket(`${wsScheme}://${window.location.host}/ws/notifications/`);
            notificationSocket.onmessage = function(event) {
                const payload = JSON.parse(event.data || "{}");
                latestNotificationId = Math.max(latestNotificationId, Number(payload.id) || latestNotificationId);
                appendToast(payload.title || "Notification", payload.message || "New update received.", "info");
            };
            notificationSocket.onopen = function() {
                pollNotifications();
            };
            notificationSocket.onclose = function() {
                startNotificationPolling();
            };
            notificationSocket.onerror = function() {};
        } catch (_) {
            startNotificationPolling();
        }
    }

    const hospitalLiveId = document.body?.dataset?.hospitalLiveId || "";
    if (hospitalLiveId) {
        const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
        const socketUrl = `${wsScheme}://${window.location.host}/ws/hospital/${hospitalLiveId}/`;
        const hospitalSectionMap = {
            shift_assignment_created: ['[data-live-section="admin-shifts"]', '[data-live-section="ops-shifts"]'],
            invitation_created: ['[data-live-section="admin-invitations"]'],
            invitation_updated: ['[data-live-section="admin-invitations"]'],
            invitation_redeemed: ['[data-live-section="admin-invitations"]'],
        };
        const scheduleHospitalRefresh = (payload = {}) => {
            window.clearTimeout(hospitalLiveRefreshTimer);
            hospitalLiveRefreshTimer = window.setTimeout(async () => {
                if (typeof refreshLiveDashboardState === "function") {
                    await refreshLiveDashboardState();
                }
                const selectors = hospitalSectionMap[payload.event_type] || [];
                if (selectors.length) {
                    await refreshLiveSections(selectors, { force: false });
                }
            }, 180);
        };
        try {
            hospitalLiveSocket = new WebSocket(socketUrl);
            hospitalLiveSocket.onmessage = function(event) {
                let payload = {};
                try {
                    payload = JSON.parse(event.data || "{}");
                } catch (_) {}
                scheduleHospitalRefresh(payload);
            };
            hospitalLiveSocket.onclose = function() {
                scheduleHospitalRefresh();
            };
            hospitalLiveSocket.onerror = function() {
                scheduleHospitalRefresh();
            };
        } catch (_) {
            scheduleHospitalRefresh();
        }
    }

    document.querySelectorAll("[data-logout-form]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector("button[type='submit']");
            if (button) {
                button.disabled = true;
                button.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`;
            }
        });
    });

    document.querySelectorAll("[data-async-cart-form]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            withBusyButton(button, "", async () => {
                const response = await fetch(getFormActionUrl(form, window.location.pathname), {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value
                    },
                    body: new FormData(form)
                });
                if (!response.ok) {
                    appendToast("Cart update failed", "The item could not be added right now.", "danger");
                    return;
                }
                const payload = await response.json();
                appendToast("Cart updated", payload.message || "Medicine added to cart.", "success");
            });
        });
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;

        if (form.matches("[data-async-status-form]")) {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            withBusyButton(button, "", async () => {
                const response = await fetch(getFormActionUrl(form), {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCsrfToken(form)
                    },
                    credentials: "same-origin",
                    body: new FormData(form)
                });
                if (!response.ok) {
                    appendToast("Update failed", "The appointment status could not be updated.", "danger");
                    return;
                }
                const payload = await response.json();
                const statusNode = document.querySelector(`[data-appointment-status="${payload.appointment_id}"]`);
                if (statusNode) {
                    const statusSlug = String(payload.status_slug || "").toLowerCase();
                    const statusIcon = statusSlug === "cancelled" ? "bi-x-circle" : "bi-check2-circle";
                    statusNode.innerHTML = `<i class="bi ${statusIcon}"></i>${escapeHtml(payload.status || payload.status_label || "Updated")}`;
                }
                const actionsNode = document.querySelector(`[data-appointment-actions="${payload.appointment_id}"]`);
                if (actionsNode && payload.status_slug) {
                    const statusSlug = String(payload.status_slug || "").toLowerCase();
                    const statusLabel = escapeHtml(payload.status || payload.status_label || "");
                    const lockButton = (button) => {
                        if (!button) return;
                        button.disabled = true;
                        button.classList.add("is-locked");
                        button.innerHTML = statusSlug === "cancelled"
                            ? `<i class="bi bi-x-circle"></i><span>${statusLabel}</span>`
                            : `<i class="bi bi-check2-circle"></i><span>${statusLabel}</span>`;
                    };
                    actionsNode.querySelectorAll("[data-async-status-form]").forEach((item) => {
                        const button = item.querySelector("button[type='submit']");
                        if (item.action.includes(`/${payload.status_slug}`)) {
                            lockButton(button);
                        }
                        else {
                            item.remove();
                        }
                    });
                }
                applyLiveMetrics(payload.metrics);
                appendToast("Appointment updated", payload.message || "Status updated.", "success");
            });
            return;
        }

        if (form.matches("[data-async-context-form]")) {
            event.preventDefault();
            const button = form.querySelector("button[type='submit']");
            withBusyButton(button, "", async () => {
                const response = await fetch(getFormActionUrl(form), {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCsrfToken(form)
                    },
                    credentials: "same-origin",
                    body: new FormData(form)
                });
                if (!response.ok) {
                    appendToast("Chart context failed", "The patient context could not be updated.", "danger");
                    return;
                }
                const payload = await response.json();
                appendToast("Chart context updated", payload.message || "Current patient set.", "success");
                if (assistantSummary) {
                    assistantSummary.textContent = `Current patient: ${payload.patient || "selected record"}.`;
                }
                syncOpenChartButtons(payload.patient_id);
            });
            return;
        }

        if (form.matches("[data-password-change-form]")) {
            event.preventDefault();
            clearInlineFormErrors(form);
            const button = form.querySelector("button[type='submit']");
            withBusyButton(button, "", async () => {
                const response = await fetch(form.getAttribute("action") || window.location.pathname, {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCsrfToken(form)
                    },
                    credentials: "same-origin",
                    body: new FormData(form)
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok || payload.ok === false) {
                    showInlineFormErrors(form, payload.errors || {});
                    appendToast("Password update failed", payload.message || "Please check the highlighted password fields.", "danger");
                    return;
                }
                appendToast("Password updated", payload.message || "Please sign in again with your new password.", "success");
                window.location.href = payload.redirect || "/login/";
            });
            return;
        }

        if (form.matches("[data-live-filter-form]")) {
            event.preventDefault();
            const submitter = event.submitter || form.querySelector("button[type='submit']");
            const actionUrl = getFormActionUrl(form, window.location.pathname);
            const refreshSelectors = parseRefreshSelectors(form.dataset.refreshSections);
            withBusyButton(submitter, "", async () => {
                const url = new URL(actionUrl, window.location.origin);
                const params = new URLSearchParams(new FormData(form));
                params.forEach((value, key) => {
                    if (value) {
                        url.searchParams.set(key, value);
                    } else {
                        url.searchParams.delete(key);
                    }
                });
                const response = await fetch(url.toString(), {
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                });
                if (!response.ok) {
                    appendToast("Filter update failed", "The schedule window could not be refreshed right now.", "danger");
                    return;
                }
                const html = await response.text().catch(() => "");
                const replaced = refreshSelectors.length ? replaceLiveSectionsWithHtml(html, refreshSelectors, { force: true }) : [];
                const swapped = replaced.length ? replaced[0] : (html ? replaceLivePageRootWithHtml(html) : null);
                if (!swapped) {
                    window.location.href = url.toString();
                    return;
                }
                window.history.replaceState({}, "", url.toString());
                appendToast(platformName, "Schedule window updated.", "success");
            });
            return;
        }

        if (form.matches("[data-async-dashboard-form]")) {
            event.preventDefault();
            clearInlineFormErrors(form);
            const button = form.querySelector("button[type='submit']");
            const behavior = form.dataset.asyncBehavior || "";
            const actionUrl = getFormActionUrl(form);
            const refreshSelectors = parseRefreshSelectors(form.dataset.refreshSections);
            withBusyButton(button, "", async () => {
                const response = await fetch(actionUrl, {
                    method: "POST",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCsrfToken(form)
                    },
                    credentials: "same-origin",
                    body: new FormData(form)
                });
                const contentType = response.headers.get("content-type") || "";
                const expectsJson = contentType.includes("application/json");
                let payload = {};
                let html = "";
                if (expectsJson) {
                    payload = await response.json().catch(() => ({}));
                    if (!response.ok || payload.ok === false) {
                        showInlineFormErrors(form, payload.errors || {});
                        if (behavior === "admission-action" && payload.html) {
                            hydrateAdmissionDashboardHtml(payload.html);
                        }
                        appendToast("Update failed", payload.message || "The dashboard action could not be completed.", "danger");
                        return;
                    }
                } else {
                    if (response.redirected && response.url && response.url !== window.location.href) {
                        window.location.href = response.url;
                        return;
                    }
                    html = await response.text().catch(() => "");
                    const swapped = html ? replaceLivePageRootWithHtml(html) : null;
                    if (!response.ok) {
                        if (swapped) {
                            appendToast("Update failed", "Please review the highlighted form fields and try again.", "danger");
                            return;
                        }
                        appendToast("Update failed", "The dashboard action could not be completed.", "danger");
                        return;
                    }
                    if (swapped) {
                        appendToast(platformName, "Dashboard updated.", "success");
                        return;
                    }
                }

                if (behavior === "medical-record") {
                    form.reset();
                } else if (behavior === "doctor-task" && payload.task) {
                    const list = document.getElementById("doctorTaskList");
                    if (list) {
                        const emptyNode = list.querySelector("[data-doctor-task-empty]");
                        if (emptyNode) emptyNode.remove();
                        list.insertAdjacentHTML("afterbegin", renderDoctorTaskCard(payload.task));
                        enhanceScrollableLists();
                    }
                    form.reset();
                } else if (behavior === "doctor-task-status" && payload.task) {
                    const actionsNode = document.querySelector(`[data-doctor-task-actions="${payload.task.id}"]`);
                    const cardNode = document.querySelector(`[data-doctor-task-card="${payload.task.id}"]`);
                    if (actionsNode && payload.task.completed) {
                        actionsNode.innerHTML = `<span class="status-pill"><i class="bi bi-check2-circle"></i>Completed</span>`;
                    }
                    if (cardNode && payload.task.completed) {
                        cardNode.classList.add("doctor-task-card-exit");
                        window.setTimeout(() => {
                            cardNode.remove();
                            syncDoctorTaskEmptyState();
                            enhanceScrollableLists();
                        }, 460);
                    } else if (actionsNode) {
                        actionsNode.innerHTML = `<span class="status-pill"><i class="bi bi-activity"></i>${escapeHtml(payload.task.status_label)}</span>`;
                    }
                } else if (behavior === "care-plan" && payload.care_plan) {
                    const list = document.getElementById("carePlanList");
                    if (list) {
                        list.insertAdjacentHTML("afterbegin", renderCarePlanCard(payload.care_plan));
                        enhanceScrollableLists();
                    }
                    form.reset();
                } else if (behavior === "internal-referral" && payload.referral) {
                    const list = document.getElementById("referralOutboundList");
                    if (list) {
                        list.insertAdjacentHTML("afterbegin", renderReferralCard(payload.referral, false));
                        enhanceScrollableLists();
                    }
                    form.reset();
                } else if (behavior === "referral-status" && payload.referral) {
                    const statusNode = document.querySelector(`[data-referral-status="${payload.referral.id}"]`);
                    if (statusNode) {
                        statusNode.textContent = payload.referral.status_label;
                    }
                    const actionsNode = document.querySelector(`[data-referral-actions="${payload.referral.id}"]`);
                    if (actionsNode) {
                        actionsNode.innerHTML = `<span class="status-pill"><i class="bi bi-check2-circle"></i>${payload.referral.status_label}</span>`;
                    }
                } else if (behavior === "admission-action") {
                    form.reset();
                const refreshed = await refreshAdmissionDashboardRoot();
                if (!refreshed) {
                    window.location.reload();
                    return;
                }
                } else if (behavior === "live-root-refresh") {
                    if (refreshSelectors.length) {
                        const replaced = await refreshLiveSections(refreshSelectors, { force: true });
                        if (!replaced.length) {
                            window.location.reload();
                            return;
                        }
                    } else if (typeof refreshCurrentPageLiveRoot === "function") {
                        form.dataset.liveRefreshAllow = "1";
                        let refreshed = null;
                        try {
                            refreshed = await refreshCurrentPageLiveRoot({ force: true });
                        } finally {
                            delete form.dataset.liveRefreshAllow;
                        }
                        if (!refreshed) {
                            window.location.reload();
                            return;
                        }
                    } else {
                        window.location.reload();
                        return;
                    }
                }

                applyLiveMetrics(payload.metrics);
                appendToast(platformName, payload.message || "Dashboard updated.", "success");
            });
        }
    });

    const liveDashboardNode = document.querySelector("[data-live-dashboard-endpoint]");
    if (liveDashboardNode) {
        const endpoint = liveDashboardNode.dataset.liveDashboardEndpoint;
        refreshLiveDashboardState = async () => {
            if (document.hidden || !endpoint) return;
            try {
                const response = await fetch(endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" });
                if (!response.ok) return;
                const payload = await response.json();
                applyLiveMetrics(payload.metrics);
                applyBayafyaWatchItems(payload.watch_items);
                return payload;
            } catch (_) {
                return null;
            }
        };
        refreshLiveDashboardState();
        window.setInterval(() => {
            if (typeof refreshLiveDashboardState === "function") {
                refreshLiveDashboardState();
            }
        }, 15000);
    }

    syncDoctorTaskEmptyState();
    initStaffCommunications();
    initBayafyaWatch();
    initMobileBottomNav();
    initAdmissionActionWorkspace();
    initAdmissionDependentSelectors();
    initRotatingCardStacks();
    initSidenavLinks();
});
