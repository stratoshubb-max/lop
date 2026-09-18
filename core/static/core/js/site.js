(() => {
    const feedList = document.getElementById('feedList');
    const postInput = document.getElementById('postInput');
    const publishButton = document.getElementById('publishButton');
    const charCount = document.getElementById('charCount');
    const toast = document.getElementById('toast');
    const toastMessage = document.getElementById('toastMessage');
    const searchLayer = document.getElementById('searchLayer');
    const searchInput = document.getElementById('searchInput');
    const searchHint = document.getElementById('searchHint');
    const filteredEmpty = document.getElementById('filteredEmpty');
    const authLayer = document.getElementById('authLayer');
    const authForm = document.getElementById('authForm');
    const authError = document.getElementById('authError');
    const authSubmit = document.getElementById('authSubmit');
    const authStatus = document.querySelector('meta[name="auth-status"]')?.content === 'true';
    let authMode = 'login';
    const formatter = new Intl.NumberFormat('ar-EG', { useGrouping: false });
    let toastTimer;
    let currentTab = 'all';
    let searchTerm = '';
    let searchTimer;
    let isPublishing = false;
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    function readCookie(name) {
        const prefix = `${name}=`;
        const value = document.cookie.split('; ').find(item => item.startsWith(prefix));
        return value ? decodeURIComponent(value.slice(prefix.length)) : '';
    }

    function apiHeaders() {
        return {
            'Content-Type': 'application/json',
            'X-CSRFToken': readCookie('csrftoken') || csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        };
    }

    async function parseApiResponse(response) {
        // Read as text first: Django's debug/CSRF pages are HTML even when a client expected JSON.
        // Parsing manually keeps raw "Unexpected token <" errors out of the user-facing UI.
        const raw = await response.text();
        if (!raw.trim()) return {};
        try {
            return JSON.parse(raw);
        } catch (error) {
            return { error: response.status === 403 ? 'انتهت صلاحية الحماية، أعد المحاولة.' : 'تعذّر الاتصال بالخادم.' };
        }
    }

    async function ensureCsrfCookie() {
        await fetch('/api/csrf/', { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    }

    async function apiRequest(url, options = {}, retry = true) {
        const response = await fetch(url, { ...options, credentials: 'same-origin' });
        const payload = await parseApiResponse(response);
        if (response.status === 403 && retry) {
            await ensureCsrfCookie();
            return apiRequest(url, { ...options, headers: { ...options.headers, ...apiHeaders() } }, false);
        }
        return { response, payload };
    }

    const icons = {
        reply: '<svg viewBox="0 0 24 24" fill="none"><path d="M20 11.3a7 7 0 0 1-7.5 6.7 8.4 8.4 0 0 1-3.3-.7L5 19l.9-3.1A6.5 6.5 0 0 1 4 11.3 7 7 0 0 1 11.5 5 7 7 0 0 1 20 11.3Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        repost: '<svg viewBox="0 0 24 24" fill="none"><path d="m7 7-3 3 3 3M4 10h10a4 4 0 0 1 4 4M17 17l3-3-3-3m3 3H10a4 4 0 0 1-4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        like: '<svg viewBox="0 0 24 24" fill="none"><path d="M20.8 8.6c0 5.3-8.8 10-8.8 10s-8.8-4.7-8.8-10a4.5 4.5 0 0 1 8.8-1.5 4.5 4.5 0 0 1 8.8 1.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        bookmark: '<svg viewBox="0 0 24 24" fill="none"><path d="M6 5.8A1.8 1.8 0 0 1 7.8 4h8.4A1.8 1.8 0 0 1 18 5.8V20l-6-3.6L6 20V5.8Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        share: '<svg viewBox="0 0 24 24" fill="none"><circle cx="18" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.6"/><circle cx="6" cy="12" r="2.5" stroke="currentColor" stroke-width="1.6"/><circle cx="18" cy="18.5" r="2.5" stroke="currentColor" stroke-width="1.6"/><path d="m8.3 10.8 7.4-4M8.3 13.2l7.4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
        verified: '<span class="verified" title="حساب موثّق"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 2 1.3 2.3-.1.9 2.1 1.9 1.2-.5 2.2.7 2.2-1.6 1.6-.2 2.3-2.2.5L12 17l-2 .9L8.1 17l-2.2-.5-.2-2.3.7-2.2-1.6-1.6 1.9-1.2.9-2.1 2.3.1L10 2Z" fill="currentColor"/><path d="m7.1 10.1 1.8 1.8 4-4" stroke="#101114" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>'
    };

    function number(value) {
        return formatter.format(Number(value) || 0);
    }

    function numericValue(value) {
        const arabicDigits = '٠١٢٣٤٥٦٧٨٩';
        const persianDigits = '۰۱۲۳۴۵۶۷۸۹';
        const normalized = String(value ?? '')
            .replace(/[٠-٩]/g, digit => String(arabicDigits.indexOf(digit)))
            .replace(/[۰-۹]/g, digit => String(persianDigits.indexOf(digit)))
            .replace(/[^0-9-]/g, '');
        return Number(normalized) || 0;
    }

    function showToast(message) {
        if (!toast || !toastMessage) return;
        toastMessage.textContent = message;
        toast.classList.remove('is-visible');
        // Re-run the entrance motion when a second notification arrives quickly.
        void toast.offsetWidth;
        toast.classList.add('is-visible');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2800);
    }

    function setAuthMode(mode = 'login') {
        authMode = mode;
        const register = mode === 'register';
        const displayField = document.querySelector('.auth-display-field');
        const handleField = document.querySelector('.auth-handle-field');
        const usernameField = document.getElementById('authUsername')?.closest('.auth-field');
        const displayName = document.getElementById('authDisplayName');
        const authHandle = document.getElementById('authHandle');
        const title = document.getElementById('authTitle');
        if (displayField) displayField.hidden = !register;
        if (handleField) handleField.hidden = !register;
        if (usernameField) usernameField.hidden = register;
        if (displayName) displayName.required = register;
        if (authHandle) authHandle.required = register;
        const username = document.getElementById('authUsername');
        if (username) username.required = !register;
        if (title) title.textContent = register ? 'مساحتك تبدأ من هنا.' : 'مرحبًا بعودتك.';
        if (authSubmit) authSubmit.innerHTML = register ? 'إنشاء الحساب <span>↗</span>' : 'تسجيل الدخول <span>↗</span>';
        document.querySelectorAll('[data-auth-tab]').forEach(tab => {
            const active = tab.dataset.authTab === mode;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (authError) authError.hidden = true;
    }

    function openAuth(mode = 'login') {
        if (!authLayer) return;
        setAuthMode(mode);
        authLayer.hidden = false;
        document.body.style.overflow = 'hidden';
        window.setTimeout(() => {
            const target = mode === 'register' ? document.getElementById('authDisplayName') : document.getElementById('authUsername');
            target?.focus();
        }, 40);
    }

    function closeAuth() {
        if (!authLayer) return;
        authLayer.hidden = true;
        document.body.style.overflow = '';
    }

    function requireAuthentication(mode = 'register') {
        if (authStatus) return false;
        openAuth(mode);
        showToast('سجّل الدخول لتتفاعل مع المنشورات');
        return true;
    }

    function replayClass(element, className, duration = 700) {
        if (!element) return;
        element.classList.remove(className);
        void element.offsetWidth;
        element.classList.add(className);
        window.setTimeout(() => element.classList.remove(className), duration);
    }

    function createRipple(element, event) {
        if (!element || element.matches(':disabled')) return;
        const rect = element.getBoundingClientRect();
        const ripple = document.createElement('span');
        ripple.className = 'interaction-ripple';
        ripple.style.left = `${event.clientX - rect.left}px`;
        ripple.style.top = `${event.clientY - rect.top}px`;
        element.appendChild(ripple);
        window.setTimeout(() => ripple.remove(), 620);
    }

    function escapeHTML(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function updateComposerState() {
        if (!postInput || !publishButton || !charCount) return;
        const length = postInput.value.length;
        charCount.textContent = `${number(length)}/${number(500)}`;
        publishButton.disabled = !postInput.value.trim() || isPublishing;
        postInput.style.height = 'auto';
        postInput.style.height = `${Math.min(Math.max(postInput.scrollHeight, 48), 170)}px`;
    }

    function renderPost(post) {
        const article = document.createElement('article');
        const tags = Array.isArray(post.tags) ? post.tags : [];
        article.className = 'post-card';
        article.dataset.postId = post.id || `local-${Date.now()}`;
        article.dataset.following = post.following ? 'true' : 'false';
        article.dataset.searchable = `${post.author_name} ${post.handle} ${post.body}`;
        article.innerHTML = `
            <div class="post-header">
                <span class="avatar avatar-large tone-${escapeHTML(post.avatar_tone || 'lime')}">${escapeHTML(post.avatar_initial || 'أ')}</span>
                <div class="post-author">
                    <div class="author-line">
                        <strong>${escapeHTML(post.author_name || 'أنت')}</strong>
                        ${post.verified ? icons.verified : ''}
                        <span class="post-handle">@${escapeHTML(post.handle || 'you')}</span>
                    </div>
                    <div class="post-meta"><span>${escapeHTML(post.published_label || 'الآن')}</span><i></i><span>عام</span></div>
                </div>
                <button class="more-button" type="button" data-toast="خيارات المنشور" data-requires-auth aria-label="المزيد"><svg viewBox="0 0 24 24" fill="none"><circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/></svg></button>
            </div>
            <div class="post-body">
                <p>${escapeHTML(post.body || '')}</p>
                ${tags.length ? `<div class="post-tags">${tags.map(tag => `<span>#${escapeHTML(tag)}</span>`).join('')}</div>` : ''}
            </div>
            <div class="post-actions">
                <button class="post-action action-reply" type="button" data-action="reply" aria-label="الرد على المنشور">${icons.reply}<span data-count="replies">${number(post.replies)}</span></button>
                <button class="post-action action-repost${post.is_reposted ? ' is-active' : ''}" type="button" data-action="repost" aria-label="إعادة نشر">${icons.repost}<span data-count="reposts">${number(post.reposts)}</span></button>
                <button class="post-action action-like${post.is_liked ? ' is-active' : ''}" type="button" data-action="like" aria-label="الإعجاب بالمنشور">${icons.like}<span data-count="likes">${number(post.likes)}</span></button>
                <button class="post-action action-bookmark${post.is_bookmarked ? ' is-active' : ''}" type="button" data-action="bookmark" aria-label="حفظ المنشور">${icons.bookmark}</button>
                <button class="post-action action-share" type="button" data-action="share" aria-label="مشاركة المنشور">${icons.share}</button>
            </div>`;
        return article;
    }

    function applyPostState(card, post) {
        if (!card || !post) return;
        const counts = { likes: post.likes, reposts: post.reposts, replies: post.replies };
        Object.entries(counts).forEach(([key, value]) => {
            const count = card.querySelector(`[data-count="${key}"]`);
            if (count) count.textContent = number(value);
        });
        const states = [
            ['like', post.is_liked],
            ['repost', post.is_reposted],
            ['bookmark', post.is_bookmarked]
        ];
        states.forEach(([type, active]) => {
            card.querySelector(`[data-action="${type}"]`)?.classList.toggle('is-active', Boolean(active));
        });
        card.dataset.following = post.following ? 'true' : 'false';
    }

    async function syncPostAction(card, actionType) {
        const { response, payload } = await apiRequest(`/api/posts/${encodeURIComponent(card.dataset.postId)}/${actionType}/`, {
            method: 'POST',
            headers: apiHeaders(),
            body: JSON.stringify({})
        });
        if (!response.ok) {
            if (payload.requires_auth) openAuth('login');
            throw new Error(payload.error || 'تعذّر حفظ التغيير');
        }
        applyPostState(card, payload.post);
        return payload;
    }

    async function toggleFollow(handle, button, wasFollowing) {
        const { response, payload } = await apiRequest(`/api/profiles/${encodeURIComponent(handle)}/follow/`, {
            method: 'POST',
            headers: apiHeaders(),
            body: JSON.stringify({})
        });
        if (!response.ok) {
            if (payload.requires_auth) openAuth('login');
            throw new Error(payload.error || 'تعذّرت متابعة الحساب');
        }
        const following = Boolean(payload.following);
        button.classList.toggle('is-following', following);
        button.textContent = following ? 'تتابع' : 'تابع';
        button.setAttribute('aria-pressed', following ? 'true' : 'false');
        replayClass(button, 'is-popping', 520);
        return following;
    }

    function updateVisibility() {
        if (!feedList) return;
        const cards = [...feedList.querySelectorAll('.post-card')];
        let visible = 0;
        cards.forEach(card => {
            const matchesTab = currentTab === 'all' || card.dataset.following === 'true';
            const searchable = (card.dataset.searchable || card.textContent).toLocaleLowerCase('ar');
            const matchesSearch = !searchTerm || searchable.includes(searchTerm.toLocaleLowerCase('ar'));
            const shouldShow = matchesTab && matchesSearch;
            card.hidden = !shouldShow;
            if (shouldShow) visible += 1;
        });
        if (filteredEmpty) {
            filteredEmpty.hidden = visible > 0;
            filteredEmpty.textContent = searchTerm
                ? `لم نعثر على نتائج لـ «${searchTerm}». جرّب كلمة أخرى.`
                : 'لا يوجد شيء هنا بعد. جرّب تبويب «لك».';
        }
    }

    async function publishPost() {
        if (!postInput || !publishButton || isPublishing) return;
        const body = postInput.value.trim();
        if (!body) return;
        const replyTo = postInput.dataset.replyTo || '';
        isPublishing = true;
        updateComposerState();
        publishButton.textContent = replyTo ? 'جارٍ الرد…' : 'جارٍ النشر…';
        try {
            const endpoint = replyTo ? `/api/posts/${encodeURIComponent(replyTo)}/reply/` : '/api/posts/';
            const { response, payload } = await apiRequest(endpoint, {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify({ body })
            });
            if (!response.ok) {
                if (payload.requires_auth) openAuth('login');
                throw new Error(payload.error || 'تعذّر الحفظ');
            }
            if (replyTo) {
                const target = feedList.querySelector(`[data-post-id="${CSS.escape(replyTo)}"]`);
                if (target) applyPostState(target, payload.post);
                showToast('وصل ردّك إلى المحادثة');
            } else {
                const card = renderPost(payload.post);
                feedList.prepend(card);
                currentTab = 'all';
                document.querySelectorAll('[data-feed-tab]').forEach(tab => {
                    const active = tab.dataset.feedTab === 'all';
                    tab.classList.toggle('is-active', active);
                    tab.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                updateVisibility();
                showToast('تركْت أثرًا جديدًا في المساحة');
            }
            postInput.value = '';
            delete postInput.dataset.replyTo;
            resetComposerMode();
        } catch (error) {
            showToast(error.message || 'حدث خطأ غير متوقع');
        } finally {
            isPublishing = false;
            publishButton.textContent = 'انشر الأثر';
            updateComposerState();
        }
    }

    function openSearch(value = '') {
        if (!searchLayer || !searchInput) return;
        searchLayer.hidden = false;
        document.body.style.overflow = 'hidden';
        searchInput.value = value;
        searchTerm = value.trim();
        filterFromSearch();
        window.setTimeout(() => searchInput.focus(), 40);
    }

    function closeSearch() {
        if (!searchLayer) return;
        searchLayer.hidden = true;
        document.body.style.overflow = '';
    }

    async function loadSearchResults(query) {
        try {
            const { response, payload } = await apiRequest(`/api/posts/?q=${encodeURIComponent(query)}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!response.ok || query !== searchTerm) return;
            feedList.replaceChildren(...payload.posts.map(renderPost));
            updateVisibility();
        } catch (error) {
            // Keep the local filter visible if the network is temporarily unavailable.
            updateVisibility();
        }
    }

    function filterFromSearch() {
        if (!searchInput) return;
        searchTerm = searchInput.value.trim();
        if (searchHint) {
            searchHint.textContent = searchTerm
                ? `نتائج البحث عن «${searchTerm}» تتحدث مع كل حرف.`
                : 'اكتب كلمة للبحث في الأصوات والمنشورات والمواضيع.';
        }
        updateVisibility();
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => loadSearchResults(searchTerm), 180);
    }

    function setComposerMode(isReply) {
        const label = document.querySelector('.compose-heading .section-label');
        if (label) label.textContent = isReply ? 'ردّك' : 'بصوتك';
        if (postInput) postInput.placeholder = isReply ? 'اكتب ردّك على هذا الأثر…' : 'ما الأثر الذي تريد أن تتركه اليوم؟';
        if (publishButton) publishButton.textContent = isReply ? 'أرسل الرد' : 'انشر الأثر';
    }

    function resetComposerMode() {
        setComposerMode(false);
    }

    function scrollToComposer() {
        const composer = document.getElementById('composeCard');
        if (!composer) return;
        composer.scrollIntoView({ behavior: 'smooth', block: 'center' });
        window.setTimeout(() => postInput?.focus(), 450);
    }

    // Composer events
    postInput?.addEventListener('input', updateComposerState);
    postInput?.addEventListener('keydown', event => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') publishPost();
    });
    publishButton?.addEventListener('click', publishPost);
    updateComposerState();

    document.addEventListener('pointerdown', event => {
        const target = event.target.closest('.post-action, .side-nav-item, .side-nav-cta, .mobile-nav-item, .mobile-nav-compose, .header-cta, .publish-button, .landing-button, .follow-button, .feed-view-button, .tool-button');
        if (target) createRipple(target, event);
    });

    // One delegated listener keeps dynamically published posts interactive too.
    document.addEventListener('click', event => {
        const openComposer = event.target.closest('[data-open-composer]');
        if (openComposer) {
            event.preventDefault();
            if (!requireAuthentication('register')) scrollToComposer();
            return;
        }

        const authTrigger = event.target.closest('[data-open-auth]');
        if (authTrigger) {
            event.preventDefault();
            openAuth(authTrigger.dataset.authMode || 'login');
            return;
        }

        const closeAuthButton = event.target.closest('[data-close-auth]');
        if (closeAuthButton) {
            closeAuth();
            return;
        }

        const authTab = event.target.closest('[data-auth-tab]');
        if (authTab) {
            setAuthMode(authTab.dataset.authTab || 'login');
            return;
        }

        const protectedTarget = event.target.closest('[data-requires-auth]');
        if (protectedTarget && requireAuthentication('login')) return;

        const toastTarget = event.target.closest('[data-toast]');
        if (toastTarget) {
            event.preventDefault();
            showToast(toastTarget.dataset.toast);
            return;
        }

        const follow = event.target.closest('[data-follow-button]');
        if (follow) {
            if (requireAuthentication('login')) return;
            const wasFollowing = follow.classList.contains('is-following');
            const handle = follow.dataset.handle;
            follow.classList.toggle('is-following', !wasFollowing);
            follow.textContent = wasFollowing ? 'تابع' : 'تتابع';
            follow.setAttribute('aria-pressed', wasFollowing ? 'false' : 'true');
            follow.disabled = true;
            toggleFollow(handle, follow, wasFollowing)
                .then(following => showToast(following ? 'أضفناه إلى دوائرك' : 'أزلناه من دوائرك'))
                .catch(error => {
                    follow.classList.toggle('is-following', wasFollowing);
                    follow.textContent = wasFollowing ? 'تتابع' : 'تابع';
                    follow.setAttribute('aria-pressed', wasFollowing ? 'true' : 'false');
                    showToast(error.message || 'لم يتم حفظ التغيير');
                })
                .finally(() => { follow.disabled = false; });
            return;
        }

        const topic = event.target.closest('[data-topic]');
        if (topic) {
            openSearch(topic.dataset.topic || '');
            return;
        }

        const nav = event.target.closest('[data-nav]');
        if (nav) {
            event.preventDefault();
            document.querySelectorAll('[data-nav]').forEach(item => item.classList.toggle('is-active', item === nav));
            const destination = nav.dataset.nav === 'discover' ? document.getElementById('discover') : nav.dataset.nav === 'circles' ? document.getElementById('circles') : document.getElementById('feed');
            destination?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            if (nav.dataset.nav !== 'home') showToast(nav.dataset.nav === 'discover' ? 'اكتشف ما يتحرك الآن' : 'دوائرك الأقرب إلى صوتك');
            return;
        }

        const tab = event.target.closest('[data-feed-tab]');
        if (tab) {
            currentTab = tab.dataset.feedTab || 'all';
            document.querySelectorAll('[data-feed-tab]').forEach(item => {
                const active = item === tab;
                item.classList.toggle('is-active', active);
                item.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            updateVisibility();
            return;
        }

        const closeSearchButton = event.target.closest('[data-close-search]');
        if (closeSearchButton) {
            closeSearch();
            return;
        }

        const action = event.target.closest('[data-action]');
        if (!action) return;
        const card = action.closest('.post-card');
        if (!card) return;

        const actionType = action.dataset.action;
        if (['like', 'repost', 'bookmark', 'reply', 'share'].includes(actionType) && requireAuthentication('login')) return;
        if (actionType === 'like' || actionType === 'repost' || actionType === 'bookmark') {
            const wasActive = action.classList.contains('is-active');
            const countKey = actionType === 'like' ? 'likes' : actionType === 'repost' ? 'reposts' : null;
            action.classList.toggle('is-active', !wasActive);
            if (countKey) {
                const count = action.querySelector(`[data-count="${countKey}"]`);
                if (count) count.textContent = number(numericValue(count.textContent) + (wasActive ? -1 : 1));
            }
            replayClass(action, actionType === 'like' ? 'is-popping' : actionType === 'repost' ? 'is-spinning' : 'is-dropping', 620);
            action.disabled = true;
            syncPostAction(card, actionType)
                .then(payload => {
                    const active = payload.active;
                    showToast(actionType === 'like' ? (active ? 'وصل إعجابك' : 'أزيل إعجابك') : actionType === 'repost' ? (active ? 'أعدت نشر هذا الأثر' : 'أزلت إعادة النشر') : (active ? 'حُفظ في مجموعتك' : 'أزيل من مجموعتك'));
                })
                .catch(error => {
                    action.classList.toggle('is-active', wasActive);
                    if (countKey) {
                        const count = action.querySelector(`[data-count="${countKey}"]`);
                        if (count) count.textContent = number(numericValue(count.textContent) + (wasActive ? 1 : -1));
                    }
                    showToast(error.message || 'لم يتم حفظ التغيير');
                })
                .finally(() => { action.disabled = false; });
            return;
        }
        if (actionType === 'reply') {
            if (postInput) postInput.dataset.replyTo = card.dataset.postId;
            setComposerMode(true);
            scrollToComposer();
            showToast('اكتب ردّك في مساحة الكتابة');
            return;
        }
        if (actionType === 'share') {
            replayClass(action, 'is-spinning', 620);
            const text = card.querySelector('.post-body p')?.textContent || '';
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(() => showToast('نُسخ الأثر إلى الحافظة')).catch(() => showToast('الأثر جاهز للمشاركة'));
            } else {
                showToast('الأثر جاهز للمشاركة');
            }
        }
    });

    document.getElementById('searchTrigger')?.addEventListener('click', () => openSearch());
    searchInput?.addEventListener('input', filterFromSearch);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && searchLayer && !searchLayer.hidden) closeSearch();
        if (event.key === 'Escape' && authLayer && !authLayer.hidden) closeAuth();
        if (event.key === '/' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
            event.preventDefault();
            openSearch();
        }
    });

    authForm?.addEventListener('submit', async event => {
        event.preventDefault();
        if (!authSubmit) return;
        const displayName = document.getElementById('authDisplayName')?.value.trim() || '';
        const handle = document.getElementById('authHandle')?.value.trim().toLowerCase() || '';
        const username = document.getElementById('authUsername')?.value.trim() || '';
        const password = document.getElementById('authPassword')?.value || '';
        const payload = authMode === 'register'
            ? { display_name: displayName, handle, password }
            : { username, password };
        authSubmit.disabled = true;
        if (authError) authError.hidden = true;
        try {
            const { response, payload: result } = await apiRequest(`/api/auth/${authMode}/`, {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify(payload)
            });
            if (!response.ok) throw new Error(result.error || 'تعذّر إكمال العملية');
            window.location.reload();
        } catch (error) {
            if (authError) {
                authError.textContent = error.message;
                authError.hidden = false;
            }
        } finally {
            authSubmit.disabled = false;
        }
    });

})();
