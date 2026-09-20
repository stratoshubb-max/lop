/* Athar — front-end application
 * Handles: feed loading & pagination, composer (text/image/AI), posts actions,
 * profile pictures, profile tabs, follow graph, search, settings and the
 * Athar assistant drawer.
 */
(() => {
    'use strict';

    // --------------------------------------------------------------------- //
    // Tiny helpers
    // --------------------------------------------------------------------- //
    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
    const MAX_LENGTH = parseInt($('meta[name="max-post-length"]')?.content || '500', 10);

    const escapeHTML = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

    const number = (value) => String(Number(value) || 0);
    const url = (text) => escapeHTML(text).replace(/(https?:\/\/[^\s<]+)/g,
        '<a class="body-link" href="$1" target="_blank" rel="noopener nofollow noreferrer">$1</a>');
    const linkify = (text) => url(String(text ?? ''))
        .replace(/(^|\s)#([\w\u0600-\u06FF_]{1,40})/g, '$1<button type="button" class="body-tag" data-topic="$2">#$2</button>')
        .replace(/(^|\s)@([a-zA-Z0-9_.-]{1,30})/g, '$1<a class="body-mention" href="/u/$2/">@$2</a>')
        .replace(/\n/g, '<br>');

    const timeAgo = (iso) => {
        if (!iso) return '';
        const then = new Date(iso);
        if (Number.isNaN(then.getTime())) return '';
        const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000);
        if (seconds < 45) return 'Just now';
        if (seconds < 90) return '1 min';
        if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
        if (seconds < 7200) return '1 h';
        if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
        if (seconds < 172800) return 'Yesterday';
        if (seconds < 604800) return `${Math.floor(seconds / 86400)} d`;
        const options = { month: 'short', day: 'numeric' };
        if (then.getFullYear() !== new Date().getFullYear()) options.year = 'numeric';
        return then.toLocaleDateString('en-US', options);
    };

    const readCookie = (name) => {
        const prefix = `${name}=`;
        const entry = document.cookie.split('; ').find((item) => item.startsWith(prefix));
        return entry ? decodeURIComponent(entry.slice(prefix.length)) : '';
    };

    const store = {
        get(key, fallback = '') {
            try { return localStorage.getItem(key) ?? fallback; } catch (error) { return fallback; }
        },
        set(key, value) {
            try { localStorage.setItem(key, value); } catch (error) { /* ignore */ }
        },
        remove(key) {
            try { localStorage.removeItem(key); } catch (error) { /* ignore */ }
        },
    };

    const state = {
        authenticated: $('meta[name="auth-status"]')?.content === 'true',
        viewerHandle: $('meta[name="viewer-handle"]')?.content || '',
        page: document.body.dataset.page || 'home',
        profileHandle: document.body.dataset.profileHandle || '',
        threadPostId: document.body.dataset.postId || '',
        tab: $('#feedList')?.dataset.tab || 'all',
        sort: $('#feedList')?.dataset.sort || 'latest',
        offset: parseInt($('#feedList')?.dataset.offset || '0', 10) || 0,
        query: '',
        topic: '',
        hasMore: true,
        loading: false,
        replyTarget: '',
        pendingAvatar: '',
        removeAvatar: false,
        attachingImage: '',
        aiAction: 'coach',
        aiText: '',
        aiResult: null,
        suggestedTags: [],
        activeCard: null,
        continuation: '',
        composeScore: 0,
        composeBusy: false,
    };

    // --------------------------------------------------------------------- //
    // Toast
    // --------------------------------------------------------------------- //
    const toast = $('#toast');
    const toastMessage = $('#toastMessage');
    let toastTimer;
    function showToast(message, tone = 'default') {
        if (!toast || !toastMessage) return;
        toastMessage.textContent = message;
        toast.dataset.tone = tone;
        toast.classList.add('is-visible');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 3200);
    }

    // --------------------------------------------------------------------- //
    // Session token & API layer
    // --------------------------------------------------------------------- //
    function getToken() { return store.get('athar_session_token'); }
    function setToken(token) {
        if (token) store.set('athar_session_token', token);
        else store.remove('athar_session_token');
    }

    (function syncTokenFromUrl() {
        const params = new URLSearchParams(window.location.search);
        const urlToken = params.get('auth_token');
        if (urlToken) {
            setToken(urlToken);
            params.delete('auth_token');
            const search = params.toString();
            window.history.replaceState({}, document.title,
                window.location.pathname + (search ? `?${search}` : '') + window.location.hash);
            return;
        }
        if (!state.authenticated && getToken()) {
            const separator = window.location.search ? '&' : '?';
            window.location.replace(`${window.location.pathname}${window.location.search}${separator}auth_token=${encodeURIComponent(getToken())}${window.location.hash}`);
        }
    })();

    function apiHeaders(extra = {}) {
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': readCookie('csrftoken') || $('meta[name="csrf-token"]')?.content || '',
            'X-Requested-With': 'XMLHttpRequest',
            ...extra,
        };
        const token = getToken();
        if (token) {
            headers['X-Session-Token'] = token;
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    }

    async function parseResponse(response) {
        const raw = await response.text();
        if (!raw.trim()) return {};
        try { return JSON.parse(raw); } catch (error) {
            return { error: response.status === 403 ? 'Security check failed — reload the page.' : 'Could not reach the server.' };
        }
    }

    async function apiRequest(path, options = {}, retry = true) {
        let response;
        try {
            response = await fetch(path, { credentials: 'same-origin', ...options });
        } catch (error) {
            return { response: { ok: false, status: 0 }, payload: { error: 'You appear to be offline.' } };
        }
        let payload = await parseResponse(response);
        if (response.status === 403 && retry && (payload.csrf_failed || !payload.error)) {
            await fetch('/api/csrf/', { credentials: 'same-origin' });
            return apiRequest(path, { ...options, headers: apiHeaders(options.headers) }, false);
        }
        if (response.status === 401 && payload.requires_auth) {
            setToken('');
            state.authenticated = false;
            openAuth('login');
            showToast('Your session ended — please sign in again.');
        }
        return { response, payload };
    }

    const apiGet = (path) => apiRequest(path, { headers: apiHeaders() });
    const apiPost = (path, body = {}) => apiRequest(path, { method: 'POST', headers: apiHeaders(), body: JSON.stringify(body) });

    // --------------------------------------------------------------------- //
    // Modal infrastructure
    // --------------------------------------------------------------------- //
    const layers = {
        search: $('#searchLayer'),
        auth: $('#authLayer'),
        settings: $('#websiteSettingsModal'),
        profile: $('#profileSettingsModal'),
        people: $('#peopleModal'),
        topics: $('#topicsModal'),
        ai: $('#aiLayer'),
    };
    const scrollLocks = new Set();

    function lockScroll(key) {
        scrollLocks.add(key);
        document.body.classList.add('has-layer');
        document.body.style.overflow = 'hidden';
    }
    function unlockScroll(key) {
        scrollLocks.delete(key);
        if (!scrollLocks.size) {
            document.body.classList.remove('has-layer');
            document.body.style.overflow = '';
        }
    }
    // --------------------------------------------------------------------- //
    // Confirmation dialog (never relies on window.confirm, which is blocked
    // inside sandboxed iframes such as hosted previews).
    // --------------------------------------------------------------------- //
    const confirmLayer = $('#confirmLayer');
    let confirmResolver = null;

    function askConfirm({ title, body, accept = 'Delete' } = {}) {
        if (!confirmLayer || !confirmLayer.isConnected) {
            return Promise.resolve(window.confirm(title || 'Are you sure?'));
        }
        const titleNode = $('#confirmTitle');
        const bodyNode = $('#confirmBody');
        const acceptButton = $('#confirmAccept');
        if (titleNode) titleNode.textContent = title || 'Are you sure?';
        if (bodyNode) {
            bodyNode.textContent = body || '';
            bodyNode.hidden = !body;
        }
        if (acceptButton) acceptButton.textContent = accept;
        openLayer(confirmLayer, 'confirm');
        window.setTimeout(() => acceptButton?.focus(), 40);
        return new Promise((resolve) => { confirmResolver = resolve; });
    }

    function settleConfirm(result) {
        if (!confirmResolver) return;
        const resolve = confirmResolver;
        confirmResolver = null;
        closeLayer(confirmLayer, 'confirm');
        resolve(result);
    }

    let lastFocused = null;

    function openLayer(element, key) {
        if (!element) return;
        if (document.activeElement instanceof window.HTMLElement && !element.contains(document.activeElement)) {
            lastFocused = document.activeElement;
        }
        element.hidden = false;
        element.classList.remove('is-hidden');
        element.style.display = '';
        lockScroll(key);
        window.setTimeout(() => {
            const focusable = element.querySelector('input, textarea, button:not([disabled])');
            focusable?.focus();
        }, 30);
    }
    function closeLayer(element, key) {
        if (!element) return;
        // Return focus to whatever opened the layer, otherwise the hidden input
        // keeps focus and keyboard shortcuts stop working.
        const hadFocus = element.contains(document.activeElement);
        element.hidden = true;
        element.classList.add('is-hidden');
        element.style.display = 'none';
        unlockScroll(key);
        if (hadFocus) {
            const restore = lastFocused && lastFocused.isConnected && !element.contains(lastFocused) ? lastFocused : null;
            if (restore) restore.focus();
            else if (document.activeElement instanceof window.HTMLElement) document.activeElement.blur();
        }
    }

    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Tab') return;
        const active = $$('.modal-layer:not([hidden]), .ai-layer:not([hidden]), .search-layer:not([hidden]), .auth-layer:not([hidden])').pop();
        if (!active) return;
        const focusables = $$('a[href], button:not([disabled]), textarea, input, select', active)
            .filter((element) => element.offsetParent !== null);
        if (!focusables.length) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    // --------------------------------------------------------------------- //
    // Theme & preferences
    // --------------------------------------------------------------------- //
    const themeCards = () => $$('[data-set-theme]');

    function setTheme(theme, persist = true) {
        if (persist) store.set('athar_theme', theme);
        const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
        const effective = theme === 'auto' ? (prefersLight ? 'light' : 'dark') : theme;
        document.documentElement.dataset.theme = effective;
        themeCards().forEach((card) => {
            const active = card.dataset.setTheme === theme;
            card.classList.toggle('is-active', active);
            card.setAttribute('aria-checked', active ? 'true' : 'false');
        });
    }

    function applyPreferences() {
        setTheme(store.get('athar_theme', 'auto'), false);

        const motion = store.get('athar_reduced_motion') === 'true';
        document.documentElement.dataset.reducedMotion = motion ? 'true' : 'false';
        const motionToggle = $('#toggleReducedMotion');
        if (motionToggle) motionToggle.checked = motion;

        const density = store.get('athar_compact_density') === 'true';
        document.documentElement.dataset.compactDensity = density ? 'true' : 'false';
        const densityToggle = $('#toggleCompactDensity');
        if (densityToggle) densityToggle.checked = density;

        const aiReplies = store.get('athar_ai_replies', 'true') === 'true';
        const aiRepliesToggle = $('#toggleAiReplies');
        if (aiRepliesToggle) aiRepliesToggle.checked = aiReplies;

        const aiTags = store.get('athar_ai_tags', 'true') === 'true';
        const aiTagsToggle = $('#toggleAiTags');
        if (aiTagsToggle) aiTagsToggle.checked = aiTags;
    }

    const aiRepliesEnabled = () => store.get('athar_ai_replies', 'true') === 'true';
    const aiTagsEnabled = () => store.get('athar_ai_tags', 'true') === 'true';

    // --------------------------------------------------------------------- //
    // Avatars
    // --------------------------------------------------------------------- //
    function avatarHTML({ avatarUrl = '', initial = 'أ', tone = 'violet', size = 'avatar-large', name = '', extra = '' }) {
        return `<span class="avatar ${size} tone-${escapeHTML(tone || 'violet')}${avatarUrl ? ' has-photo' : ''}" ${extra}>` +
            (avatarUrl
                ? `<img src="${escapeHTML(avatarUrl)}" alt="${escapeHTML(name)}" loading="lazy" decoding="async">`
                : escapeHTML(initial || 'أ')) +
            '</span>';
    }

    function refreshViewerAvatars(avatarUrl, tone) {
        $$('[data-viewer-avatar]').forEach((element) => {
            const classes = element.className.split(' ').filter((item) => !item.startsWith('tone-') && item !== 'has-photo');
            if (tone) classes.push(`tone-${tone}`);
            if (avatarUrl) classes.push('has-photo');
            element.className = classes.join(' ');
            element.innerHTML = avatarUrl
                ? `<img src="${escapeHTML(avatarUrl)}" alt="Your profile picture">`
                : (element.dataset.initials || element.textContent.trim() || 'أ');
        });
    }

    // --------------------------------------------------------------------- //
    // Post rendering
    // --------------------------------------------------------------------- //
    const icons = {
        reply: '<svg viewBox="0 0 24 24" fill="none"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        repost: '<svg viewBox="0 0 24 24" fill="none"><path d="m7 7-3 3 3 3M4 10h10a4 4 0 0 1 4 4M17 17l3-3-3-3m3 3H10a4 4 0 0 1-4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        like: '<svg viewBox="0 0 24 24" fill="none"><path d="M20.8 8.6c0 5.3-8.8 10-8.8 10s-8.8-4.7-8.8-10a4.5 4.5 0 0 1 8.8-1.5 4.5 4.5 0 0 1 8.8 1.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        bookmark: '<svg viewBox="0 0 24 24" fill="none"><path d="M6 5.8A1.8 1.8 0 0 1 7.8 4h8.4A1.8 1.8 0 0 1 18 5.8V20l-6-3.6L6 20V5.8Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>',
        share: '<svg viewBox="0 0 24 24" fill="none"><circle cx="18" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.6"/><circle cx="6" cy="12" r="2.5" stroke="currentColor" stroke-width="1.6"/><circle cx="18" cy="18.5" r="2.5" stroke="currentColor" stroke-width="1.6"/><path d="m8.3 10.8 7.4-4M8.3 13.2l7.4 4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
        verified: '<span class="verified" title="Verified account"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 2 1.3 2.3-.1.9 2.1 1.9 1.2-.5 2.2.7 2.2-1.6 1.6-.2 2.3-2.2.5L12 17l-2 .9L8.1 17l-2.2-.5-.2-2.3-1.6-1.6.7-2.2-.5-2.2 1.9-1.2.9-2.1 2.3.1L10 2Z" fill="currentColor"/><path d="m7.1 10.1 1.8 1.8 4-4" stroke="#101114" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>',
        trash: '<svg viewBox="0 0 24 24" fill="none"><path d="M19 7l-.8 12.1A2 2 0 0 1 16.2 21H7.8a2 2 0 0 1-2-1.9L5 7m5 4v6m4-6v6M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3M4 7h16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        dots: '<svg viewBox="0 0 24 24" fill="none"><circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/></svg>',
    };

    function renderPost(post) {
        const article = document.createElement('article');
        const tags = Array.isArray(post.tags) ? post.tags : [];
        const permalink = post.permalink || `/p/${post.id}/`;
        article.className = 'post-card';
        article.dataset.postId = post.id;
        article.dataset.isOwner = post.is_owner ? 'true' : 'false';
        article.dataset.following = post.following ? 'true' : 'false';
        article.dataset.handle = post.handle || '';
        article.dataset.permalink = permalink;
        article.dataset.searchable = `${post.author_name} ${post.handle} ${post.body}`;

        const ownerActions = post.is_owner
            ? '<button type="button" data-action="edit-post">Edit thought</button><button type="button" class="danger" data-action="delete-post">Delete thought</button>'
            : '<button type="button" data-action="report">Report</button>';

        article.innerHTML = `
            <div class="post-header">
                <a href="/u/${encodeURIComponent(post.handle || '')}/" class="post-header-link" aria-label="${escapeHTML(post.author_name)}">
                    ${avatarHTML({ avatarUrl: post.avatar_url, initial: post.avatar_initial, tone: post.avatar_tone, name: post.author_name })}
                </a>
                <div class="post-author">
                    <div class="author-line">
                        <a href="/u/${encodeURIComponent(post.handle || '')}/"><strong>${escapeHTML(post.author_name)}</strong></a>
                        ${post.verified ? icons.verified : ''}
                        <a href="/u/${encodeURIComponent(post.handle || '')}/"><span class="post-handle">@${escapeHTML(post.handle)}</span></a>
                        <span class="post-badge" data-follow-badge ${post.following ? '' : 'hidden'}>Following</span>
                    </div>
                    <div class="post-meta">
                        <a class="post-time" href="${permalink}" data-published-at="${escapeHTML(post.published_at || '')}">${escapeHTML(post.published_label || 'Just now')}</a><i></i><span>Public</span>
                        ${post.edited ? '<span class="post-edited">edited</span>' : ''}
                    </div>
                </div>
                <div class="post-menu-wrap">
                    <button class="more-button${post.is_owner ? ' is-owner' : ''}" type="button" data-post-menu aria-label="Thought options" aria-expanded="false">${post.is_owner ? icons.trash : icons.dots}</button>
                    <div class="post-menu" hidden>
                        <button type="button" data-action="copy-link">Copy link</button>
                        <a href="${permalink}" data-action="open-thread">Open thread</a>
                        <button type="button" data-action="ai-related">More like this</button>
                        ${ownerActions}
                    </div>
                </div>
            </div>
            <div class="post-body">
                <p class="post-text">${linkify(post.body || '')}</p>
                ${post.image_url ? `<a class="post-image-link" href="${permalink}"><img class="post-image" src="${escapeHTML(post.image_url)}" alt="Attachment shared by ${escapeHTML(post.author_name)}" loading="lazy" decoding="async"></a>` : ''}
                ${tags.length ? `<div class="post-tags">${tags.map((tag) => `<button type="button" class="post-tag" data-topic="${escapeHTML(tag)}">#${escapeHTML(tag)}</button>`).join('')}</div>` : ''}
            </div>
            <div class="post-actions">
                <button class="post-action action-reply" type="button" data-action="reply" aria-label="Reply">${icons.reply}<span data-count="replies">${number(post.replies)}</span></button>
                <button class="post-action action-repost${post.is_reposted ? ' is-active' : ''}" type="button" data-action="repost" aria-label="Repost">${icons.repost}<span data-count="reposts">${number(post.reposts)}</span></button>
                <button class="post-action action-like${post.is_liked ? ' is-active' : ''}" type="button" data-action="like" aria-label="Like">${icons.like}<span data-count="likes">${number(post.likes)}</span></button>
                <button class="post-action action-bookmark${post.is_bookmarked ? ' is-active' : ''}" type="button" data-action="bookmark" aria-label="Save">${icons.bookmark}</button>
                <button class="post-action action-share" type="button" data-action="share" aria-label="Share">${icons.share}</button>
            </div>
            <div class="inline-reply" hidden>
                <div class="inline-reply-head">
                    <span class="section-label">Replying to @${escapeHTML(post.handle)}</span>
                    <button type="button" class="mini-link" data-ai-reply-suggest>AI reply ideas</button>
                </div>
                <div class="ai-reply-chips" hidden></div>
                <textarea class="inline-reply-input" rows="2" maxlength="${MAX_LENGTH}" placeholder="Write your reply…"></textarea>
                <div class="inline-reply-actions">
                    <span class="inline-reply-count">0/${MAX_LENGTH}</span>
                    <button type="button" class="btn-ghost" data-cancel-reply>Cancel</button>
                    <button type="button" class="btn-primary btn-send-reply" disabled>Reply</button>
                </div>
            </div>`;
        return article;
    }

    function applyPostState(card, post) {
        if (!card || !post) return;
        [['likes', post.likes], ['reposts', post.reposts], ['replies', post.replies]].forEach(([key, value]) => {
            const target = card.querySelector(`[data-count="${key}"]`);
            if (target) target.textContent = number(value);
        });
        [['like', post.is_liked], ['repost', post.is_reposted], ['bookmark', post.is_bookmarked]].forEach(([type, active]) => {
            card.querySelector(`[data-action="${type}"]`)?.classList.toggle('is-active', Boolean(active));
        });
        if (typeof post.body === 'string') {
            const text = card.querySelector('.post-text');
            if (text) text.innerHTML = linkify(post.body);
            card.dataset.searchable = `${post.author_name} ${post.handle} ${post.body}`;
        }
        card.dataset.following = post.following ? 'true' : 'false';
        card.querySelector('[data-follow-badge]')?.toggleAttribute('hidden', !post.following);
        card.querySelector('.post-edited')?.remove();
        if (post.edited && !card.querySelector('.post-edited')) {
            card.querySelector('.post-meta')?.insertAdjacentHTML('beforeend', '<span class="post-edited">edited</span>');
        }
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

    // --------------------------------------------------------------------- //
    // Feed
    // --------------------------------------------------------------------- //
    const feedList = $('#feedList');
    const loadMoreButton = $('#loadMoreButton');
    const filteredEmpty = $('#filteredEmpty');

    function setFeedEmpty(message) {
        if (!feedList) return;
        feedList.innerHTML = `<div class="empty-state">${escapeHTML(message)}</div>`;
    }

    function showSkeletons(count = 3) {
        if (!feedList) return;
        feedList.innerHTML = Array.from({ length: count }).map(() => `
            <article class="post-card skeleton-card" aria-hidden="true">
                <div class="skeleton-line w-40"></div>
                <div class="skeleton-line w-90"></div>
                <div class="skeleton-line w-70"></div>
            </article>`).join('');
    }

    async function loadFeed({ append = false, quiet = false } = {}) {
        if (!feedList || state.loading) return;
        state.loading = true;
        if (loadMoreButton) loadMoreButton.disabled = true;
        if (!append && !quiet) showSkeletons();

        const params = new URLSearchParams({ tab: state.tab, sort: state.sort, limit: '20', offset: String(append ? state.offset : 0), parent: 'root' });
        if (state.query) params.set('q', state.query);
        if (state.topic) params.set('topic', state.topic);

        const { response, payload } = await apiGet(`/api/posts/?${params.toString()}`);
        state.loading = false;
        if (loadMoreButton) loadMoreButton.disabled = false;

        if (!response.ok || !Array.isArray(payload.posts)) {
            if (!append) setFeedEmpty(payload.error || 'Could not load thoughts right now.');
            return;
        }

        if (!append) feedList.innerHTML = '';
        if (payload.posts.length === 0 && !append) {
            const messages = {
                bookmarks: 'No saved thoughts yet. Tap the save icon on any thought to keep it here.',
                following: 'Your following feed is quiet. Follow a few voices to fill it.',
                likes: 'No liked thoughts yet.',
            };
            setFeedEmpty(messages[state.tab] || 'No thoughts yet. Be the first to share one.');
        } else {
            payload.posts.forEach((post) => {
                const card = renderPost(post);
                card.classList.add('is-entering');
                feedList.appendChild(card);
            });
            $$('.empty-state', feedList).forEach((element) => element.remove());
        }

        state.offset = payload.next_offset ?? state.offset + payload.posts.length;
        state.hasMore = Boolean(payload.has_more);
        if (loadMoreButton) {
            loadMoreButton.hidden = !state.hasMore;
            loadMoreButton.disabled = false;
        }
        if (filteredEmpty) filteredEmpty.hidden = state.hasMore || payload.posts.length > 0;
        refreshTimes();
    }

    function setTab(tab) {
        state.tab = tab;
        state.offset = 0;
        $$('[data-feed-tab]').forEach((item) => {
            const active = item.dataset.feedTab === tab;
            item.classList.toggle('is-active', active);
            item.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (feedList) feedList.dataset.tab = tab;
        loadFeed();
    }

    function setSort(sort, label) {
        state.sort = sort;
        const labelTarget = $('#sortLabel');
        if (labelTarget && label) labelTarget.textContent = label;
        $('#sortMenu')?.setAttribute('hidden', '');
        $('#sortButton')?.setAttribute('aria-expanded', 'false');
        state.offset = 0;
        loadFeed();
    }

    function refreshTimes() {
        $$('[data-published-at]').forEach((element) => {
            const label = timeAgo(element.dataset.publishedAt);
            if (label && label !== element.textContent.trim()) element.textContent = label;
        });
    }

    // --------------------------------------------------------------------- //
    // Composer
    // --------------------------------------------------------------------- //
    const postInput = $('#postInput');
    const publishButton = $('#publishButton');
    const charCount = $('#charCount');
    const composeCard = $('#composeCard');
    const imageInput = $('#composeImageInput');
    const imagePreview = $('#composeImagePreview');
    const imageThumb = $('#composeImageThumb');
    const imageMeta = $('#composeImageMeta');
    const imageName = $('#composeImageName');
    const emojiPicker = $('#emojiPicker');
    const inlineSuggest = $('#aiInlineSuggest');

    function updateComposerState() {
        if (!postInput || !publishButton || !charCount) return;
        const length = postInput.value.length;
        charCount.textContent = `${length}/${MAX_LENGTH}`;
        charCount.classList.toggle('is-near-limit', length > MAX_LENGTH * 0.85);
        publishButton.disabled = !postInput.value.trim() && !state.attachingImage;
        postInput.style.height = 'auto';
        postInput.style.height = `${Math.min(Math.max(postInput.scrollHeight, 48), 220)}px`;
    }

    function setComposerMode(isReply, handle = '') {
        const label = $('#composerLabel');
        if (label) label.textContent = isReply ? 'Your reply' : 'In your voice';
        if (postInput) {
            postInput.placeholder = isReply
                ? `Reply to @${handle || 'this thought'}…`
                : 'What thought do you want to leave today?';
        }
        if (publishButton) publishButton.textContent = isReply ? 'Send Reply' : 'Share Thought';
        const context = $('#composerContext');
        if (context) {
            context.hidden = !isReply;
            context.textContent = isReply ? `Replying to @${handle}` : '';
        }
        state.replyTarget = isReply ? (state.replyTarget || '') : '';
    }

    function scrollToComposer() {
        if (!composeCard) return;
        // Focus first so typing can start immediately, then bring it into view.
        try { postInput?.focus({ preventScroll: true }); } catch (error) { postInput?.focus(); }
        composeCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    function fileToDataUrl(file, { square = false, max = 1280, quality = 0.9 } = {}) {
        return new Promise((resolve, reject) => {
            if (!file.type.startsWith('image/')) {
                reject(new Error('That file is not an image.'));
                return;
            }
            const reader = new FileReader();
            reader.onerror = () => reject(new Error('Could not read that file.'));
            reader.onload = () => {
                const image = new Image();
                image.onerror = () => reject(new Error('That image could not be opened.'));
                image.onload = () => {
                    const side = square ? Math.min(image.width, image.height) : 0;
                    const sourceX = square ? (image.width - side) / 2 : 0;
                    const sourceY = square ? (image.height - side) / 2 : 0;
                    const sourceWidth = square ? side : image.width;
                    const sourceHeight = square ? side : image.height;
                    const scale = Math.min(1, max / Math.max(sourceWidth, sourceHeight));
                    const canvas = document.createElement('canvas');
                    canvas.width = Math.max(1, Math.round(sourceWidth * scale));
                    canvas.height = Math.max(1, Math.round(sourceHeight * scale));
                    const context = canvas.getContext('2d');
                    if (!context) {
                        // No canvas support: send the original and let the
                        // server-side pipeline resize and crop it.
                        resolve({ dataUrl: reader.result, width: image.width, height: image.height });
                        return;
                    }
                    context.imageSmoothingQuality = 'high';
                    context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, canvas.width, canvas.height);
                    try {
                        resolve({ dataUrl: canvas.toDataURL('image/jpeg', quality), width: canvas.width, height: canvas.height });
                    } catch (error) {
                        resolve({ dataUrl: reader.result, width: image.width, height: image.height });
                    }
                };
                image.src = reader.result;
            };
            reader.readAsDataURL(file);
        });
    }

    function attachComposeImage(dataUrl, { name = 'attachment', width = 0, height = 0, bytes = 0 } = {}) {
        state.attachingImage = dataUrl;
        if (imageThumb) imageThumb.src = dataUrl;
        if (imageName) imageName.textContent = name;
        if (imageMeta) {
            const size = bytes ? `${Math.round(bytes / 1024)} KB` : '';
            imageMeta.textContent = [width && height ? `${width}×${height}` : '', size].filter(Boolean).join(' · ');
        }
        if (imagePreview) imagePreview.hidden = false;
        updateComposerState();
    }

    function clearComposeImage() {
        state.attachingImage = '';
        if (imagePreview) imagePreview.hidden = true;
        if (imageInput) imageInput.value = '';
        updateComposerState();
    }

    async function publishPost() {
        if (!postInput || !publishButton) return;
        const body = postInput.value.trim();
        if (!body && !state.attachingImage) return;
        if (body.length > MAX_LENGTH) {
            showToast(`Thoughts are limited to ${MAX_LENGTH} characters.`, 'warn');
            return;
        }
        const isReply = Boolean(state.replyTarget);
        publishButton.disabled = true;
        publishButton.textContent = isReply ? 'Replying…' : 'Publishing…';

        const payload = { body };
        if (state.attachingImage) payload.image_data = state.attachingImage;
        if (state.suggestedTags.length) payload.tags = state.suggestedTags;

        const endpoint = isReply ? `/api/posts/${encodeURIComponent(state.replyTarget)}/reply/` : '/api/posts/';
        const { response, payload: result } = await apiPost(endpoint, payload);

        publishButton.disabled = false;
        if (!response.ok || !result.post) {
            showToast(result.error || 'Could not save your thought.', 'warn');
            publishButton.textContent = isReply ? 'Send Reply' : 'Share Thought';
            return;
        }

        postInput.value = '';
        clearComposeImage();
        clearSuggestions();
        resetComposerMode();
        updateComposerState();
        store.remove(DRAFT_KEY);

        if (isReply) {
            const target = document.querySelector(`[data-post-id="${state.replyTarget}"]`);
            if (target) applyPostState(target, result.post);
            const threadReplies = $('#threadReplies');
            if (threadReplies && result.reply) {
                threadReplies.appendChild(renderPost(result.reply));
                $$('.empty-state', threadReplies).forEach((element) => element.remove());
            }
            showToast('Your reply is now part of the conversation.');
        } else {
            if (feedList) {
                $$('.empty-state', feedList).forEach((element) => element.remove());
                feedList.prepend(renderPost(result.post));
                state.offset += 1;
            }
            showToast('You shared a new thought.');
        }
    }

    // --------------------------------------------------------------------- //
    // Drafts survive a reload (accidental refresh, phone locking, navigation)
    // --------------------------------------------------------------------- //
    const DRAFT_KEY = 'athar_draft';
    let draftTimer;

    function saveDraft() {
        if (!postInput || !state.authenticated || state.replyTarget) return;
        window.clearTimeout(draftTimer);
        draftTimer = window.setTimeout(() => {
            const value = postInput.value;
            if (value.trim()) store.set(DRAFT_KEY, value);
            else store.remove(DRAFT_KEY);
        }, 450);
    }

    function restoreDraft() {
        if (!postInput || !state.authenticated) return;
        const saved = store.get(DRAFT_KEY);
        if (!saved || postInput.value.trim()) return;
        postInput.value = saved;
        updateComposerState();
        scheduleComposeHints();
        showToast('Unfinished draft restored — publish or clear it whenever you like.');
    }

    // --------------------------------------------------------------------- //
    // Live compose assistance — inline tone, score, tags and a Tab completion
    // --------------------------------------------------------------------- //
    let composeTimer;

    function hideComposeHints() {
        state.continuation = '';
        state.composeScore = 0;
        if (inlineSuggest) {
            inlineSuggest.hidden = true;
            inlineSuggest.innerHTML = '';
        }
    }

    function scheduleComposeHints() {
        window.clearTimeout(composeTimer);
        if (!state.authenticated || !aiTagsEnabled() || !postInput) {
            hideComposeHints();
            return;
        }
        const value = postInput.value.trim();
        if (value.length < 18) {
            hideComposeHints();
            return;
        }
        composeTimer = window.setTimeout(() => runComposeHints(value), 800);
    }

    async function runComposeHints(value) {
        if (state.composeBusy) return;
        state.composeBusy = true;
        try {
            const { response, payload } = await apiPost('/api/ai/compose/', { text: value });
            if (!response.ok || !payload.ok) return;
            if (!postInput || postInput.value.trim() !== value) return;
            renderComposeHints(payload);
        } catch (error) {
            /* the composer stays fully usable without assistance */
        } finally {
            state.composeBusy = false;
        }
    }

    function renderComposeHints(payload) {
        if (!inlineSuggest || !postInput) return;
        state.aiResult = payload;
        state.continuation = payload.continuation?.text || '';
        const tone = payload.tone?.mood || 'neutral';
        const toneLabel = tone.charAt(0).toUpperCase() + tone.slice(1);
        const tags = Array.isArray(payload.hashtags) ? payload.hashtags.slice(0, 4) : [];
        inlineSuggest.hidden = false;
        inlineSuggest.innerHTML = `
            <div class="compose-hint-head">
                <span class="ai-chip">✦ ${escapeHTML(toneLabel)} · ${escapeHTML(payload.readability?.level || 'Draft')}</span>
                <span class="compose-score" title="How ready this draft is"><strong>${escapeHTML(String(payload.score ?? 0))}</strong>/100</span>
            </div>
            <p class="compose-nudge">${escapeHTML(payload.nudge || '')}</p>
            ${tags.length ? `<div class="ai-tag-row">${tags.map((tag) => `<button type="button" class="ai-tag" data-ai-tag="${escapeHTML(tag)}">#${escapeHTML(tag)}</button>`).join('')}${state.suggestedTags.length > 1 ? '' : '<button type="button" class="btn-ghost small" data-ai-apply-tags>Use all</button>'}</div>` : ''}
            ${state.continuation ? `<button type="button" class="compose-continue" data-ai-continue><em>Tab</em><span>${escapeHTML(state.continuation)}</span></button>` : ''}
        `;
    }

    function applyContinuation() {
        if (!postInput || !state.continuation) return false;
        const base = postInput.value.replace(/\s+$/, '');
        const addition = state.continuation.trim();
        if (!addition) return false;
        let joined;
        if (!base) {
            joined = addition.charAt(0).toUpperCase() + addition.slice(1);
        } else if (/[.!?]$/.test(base)) {
            joined = `${base} ${addition.charAt(0).toUpperCase()}${addition.slice(1)}`;
        } else if (/[,:;]$/.test(base)) {
            joined = `${base} ${addition}`;
        } else {
            joined = `${base} ${addition}`;
        }
        if (!/[.!?]$/.test(joined)) joined = `${joined}.`;
        postInput.value = joined;
        postInput.focus();
        postInput.setSelectionRange(joined.length, joined.length);
        state.continuation = '';
        updateComposerState();
        scheduleComposeHints();
        showToast('Line added — keep writing, or publish when it feels right.');
        return true;
    }

    function clearSuggestions() {
        state.suggestedTags = [];
        state.continuation = '';
        if (inlineSuggest) {
            inlineSuggest.hidden = true;
            inlineSuggest.innerHTML = '';
        }
    }

    function resetComposerMode() {
        state.replyTarget = '';
        setComposerMode(false, '');
    }

    // --------------------------------------------------------------------- //
    // Athar assistant
    // --------------------------------------------------------------------- //
    const aiLayer = layers.ai;
    const aiStream = $('#aiStream');
    const aiContextBox = $('#aiContext');
    const aiInsertButton = $('#aiInsertButton');

    function openAI(action = 'coach', text = '', { run = true } = {}) {
        if (!aiLayer) return;
        state.aiAction = action;
        state.aiText = text || currentDraftText();
        if (state.aiText) $('#aiContext')?.removeAttribute('hidden');
        const title = $('#aiTitle');
        if (title) title.textContent = AI_TITLES[action] || 'Your thinking partner';
        openLayer(aiLayer, 'ai');
        $$('.ai-chip-button').forEach((chip) => chip.classList.toggle('is-active', chip.dataset.aiAction === action));
        if (run) runAIAction(action);
    }

    const AI_TITLES = {
        coach: 'Your thinking partner',
        improve: 'Rewrite options',
        hashtags: 'Tags for this thought',
        tone: 'How this reads',
        shorten: 'Tighter version',
        expand: 'Develop the idea',
        reply: 'Reply ideas',
        prompts: 'Writing prompts',
        related: 'More like this',
    };

    const closeAI = () => closeLayer(aiLayer, 'ai');

    function currentDraftText() {
        const activeCard = state.activeCard;
        const inlineReply = activeCard?.querySelector('.inline-reply-input');
        if (inlineReply && !activeCard.querySelector('.inline-reply')?.hidden && inlineReply.value.trim()) {
            return inlineReply.value.trim();
        }
        return postInput?.value.trim() || '';
    }

    function aiContextLabel() {
        if (!state.aiText) return 'No draft yet — ask for prompts to get started.';
        const trimmed = state.aiText.length > 220 ? `${state.aiText.slice(0, 220)}…` : state.aiText;
        return `Working on: “${trimmed}”`;
    }

    function aiLoading(title = 'Reading your words…', note = 'Scoring keywords, tone and rhythm.') {
        if (!aiStream) return;
        aiStream.innerHTML = `
            <div class="ai-loading" role="status">
                <span class="ai-orb is-thinking" aria-hidden="true">✦</span>
                <div>
                    <strong>${escapeHTML(title)}</strong>
                    <span>${escapeHTML(note)}</span>
                </div>
            </div>`;
    }

    async function runAIAction(action, overrideText = null) {
        if (!aiStream) return;
        state.aiAction = action;
        if (overrideText !== null) state.aiText = overrideText;
        const text = state.aiText || '';
        const contextBox = aiContextBox;
        if (contextBox) {
            contextBox.hidden = !text;
            contextBox.textContent = aiContextLabel();
        }
        $$('.ai-chip-button').forEach((chip) => chip.classList.toggle('is-active', chip.dataset.aiAction === action));

        if (!text && !['prompts', 'digest', 'topics'].includes(action)) {
            aiStream.innerHTML = `
                <div class="ai-empty">
                    <span class="ai-orb" aria-hidden="true">✦</span>
                    <p>Write a few words in the composer first — then ask for a rewrite, tags or a tone check.</p>
                    <button type="button" class="btn-ai" data-ai-action="prompts">Give me a prompt instead</button>
                </div>`;
            if (aiInsertButton) aiInsertButton.hidden = true;
            return;
        }

        aiLoading();
        if (aiInsertButton) aiInsertButton.hidden = true;

        const body = { text, use_feed_context: Boolean($('#aiFeedContext')?.checked) };
        if (state.activeCard && state.page === 'thread') body.post_id = state.activeCard.dataset.postId;
        if (action === 'reply' && state.activeCard) body.post_id = state.activeCard.dataset.postId;

        const { response, payload } = await apiPost(`/api/ai/${encodeURIComponent(action)}/`, body);
        if (!response.ok || payload.error) {
            aiStream.innerHTML = `<div class="ai-error">${escapeHTML(payload.error || 'The assistant could not answer right now.')}</div>`;
            return;
        }
        state.aiResult = payload;
        renderAIResult(payload);
    }

    function suggestionCard(suggestion, { insert = 'composer' } = {}) {
        return `
            <div class="ai-suggestion">
                <div class="ai-suggestion-head">
                    <strong>${escapeHTML(suggestion.label || 'Suggestion')}</strong>
                    ${suggestion.note ? `<span>${escapeHTML(suggestion.note)}</span>` : ''}
                </div>
                <p>${linkify(suggestion.text || '')}</p>
                <div class="ai-suggestion-actions">
                    <button type="button" class="btn-primary small" data-ai-use-text="${escapeHTML(suggestion.text || '')}" data-ai-insert="${insert}">Use this</button>
                    <button type="button" class="btn-ghost small" data-ai-copy="${escapeHTML(suggestion.text || '')}">Copy</button>
                </div>
            </div>`;
    }

    function renderAIResult(payload) {
        if (!aiStream) return;
        const parts = [];
        if (payload.summary) parts.push(`<p class="ai-summary">${escapeHTML(payload.summary)}</p>`);

        if (Array.isArray(payload.notes) && payload.notes.length) {
            parts.push(`<ul class="ai-notes">${payload.notes.map((note) => `<li>${escapeHTML(note)}</li>`).join('')}</ul>`);
        }

        if (payload.tone) {
            const position = Math.round(((payload.tone.score + 1) / 2) * 100);
            parts.push(`
                <div class="ai-tone">
                    <div class="ai-tone-head"><strong>Tone</strong><span>${escapeHTML(payload.tone.mood)} · ${escapeHTML(payload.tone.label)}</span></div>
                    <div class="ai-tone-meter"><i style="left:${position}%"></i></div>
                    <p>${escapeHTML(payload.tone.advice || '')}</p>
                </div>`);
        }

        if (payload.readability) {
            parts.push(`
                <div class="ai-metrics">
                    <div><strong>${payload.readability.score}</strong><span>readability</span></div>
                    <div><strong>${payload.readability.words}</strong><span>words</span></div>
                    <div><strong>${payload.readability.avg_sentence}</strong><span>avg / sentence</span></div>
                    <div><strong>${escapeHTML(payload.readability.level)}</strong><span>level</span></div>
                </div>`);
        }

        if (Array.isArray(payload.checks) && payload.checks.length) {
            parts.push(`<div class="ai-checks">${payload.checks.map((check) => `
                <div class="ai-check is-${escapeHTML(check.level)}">
                    <strong>${escapeHTML(check.title)}</strong>
                    <span>${escapeHTML(check.message)}</span>
                </div>`).join('')}</div>`);
        }

        if (Array.isArray(payload.suggestions) && payload.suggestions.length) {
            const insertTarget = ['reply', 'replies'].includes(payload.action) ? 'reply' : 'composer';
            parts.push(`<div class="ai-suggestions">${payload.suggestions.map((suggestion) => suggestionCard(suggestion, { insert: insertTarget })).join('')}</div>`);
        }

        if (Array.isArray(payload.hashtags) && payload.hashtags.length) {
            parts.push(`
                <div class="ai-tags">
                    <span class="section-label">Suggested tags</span>
                    <div class="ai-tag-row">${payload.hashtags.map((tag) => `<button type="button" class="ai-tag" data-ai-tag="${escapeHTML(tag)}">#${escapeHTML(tag)}</button>`).join('')}</div>
                    <button type="button" class="btn-ghost small" data-ai-apply-tags>Add tags to my post</button>
                </div>`);
        }

        if (Array.isArray(payload.keywords) && payload.keywords.length) {
            parts.push(`<div class="ai-keywords"><span class="section-label">Key ideas</span><div class="ai-tag-row">${payload.keywords.map((word) => `<span class="ai-keyword">${escapeHTML(word)}</span>`).join('')}</div></div>`);
        }

        if (Array.isArray(payload.prompts) && payload.prompts.length) {
            parts.push(`<div class="ai-prompts">${payload.prompts.map((prompt) => `
                <button type="button" class="ai-prompt" data-ai-use-text="${escapeHTML(prompt)}" data-ai-insert="composer">
                    <em>Prompt</em><p>${escapeHTML(prompt)}</p>
                </button>`).join('')}</div>`);
        }

        if (Array.isArray(payload.bullets) && payload.bullets.length > 1) {
            parts.push(`<ul class="ai-notes">${payload.bullets.map((bullet) => `<li>${escapeHTML(bullet)}</li>`).join('')}</ul>`);
        }

        if (payload.provider) {
            parts.push(`<p class="ai-provider-note">Engine: ${escapeHTML(payload.provider)}</p>`);
        }

        aiStream.innerHTML = parts.join('') || '<div class="ai-empty"><p>Nothing to report — your draft reads cleanly.</p></div>';
    }

    function applyAIText(text, target) {
        if (target === 'reply') {
            const card = state.activeCard;
            const inlineInput = card?.querySelector('.inline-reply-input');
            const cardReply = card?.querySelector('.inline-reply');
            if (inlineInput && cardReply) {
                cardReply.hidden = false;
                inlineInput.value = text;
                inlineInput.dispatchEvent(new Event('input'));
                inlineInput.focus();
                closeAI();
                showToast('Reply idea inserted.');
                return;
            }
        }
        if (postInput && composeCard) {
            postInput.value = text;
            postInput.dispatchEvent(new Event('input'));
            closeAI();
            scrollToComposer();
            showToast('Added to your composer.');
            return;
        }
        showToast('Nothing to insert into.');
    }

    async function loadDigest() {
        const banner = $('#aiDigestBanner');
        const digestBox = $('#aiDigest');
        if (!banner && !digestBox) return;
        const target = digestBox || banner;
        // Only one digest surface is used at a time: the rail box when it is
        // present, otherwise the inline banner under the composer.
        if (banner && banner !== target) banner.hidden = true;
        target.hidden = false;
        target.innerHTML = '<div class="ai-loading"><span class="ai-orb is-thinking">✦</span><div><strong>Reading the feed…</strong><span>Summarising the last thoughts.</span></div></div>';
        const { response, payload } = await apiGet('/api/ai/digest/');
        if (!response.ok || !payload.digest) {
            target.innerHTML = '<div class="ai-error">The digest is unavailable right now.</div>';
            return;
        }
        const digest = payload.digest;
        target.innerHTML = `
            <div class="digest-head">
                <span class="section-label">AI digest</span>
                <span class="ai-chip">${escapeHTML(payload.provider)}</span>
            </div>
            <p class="digest-mood">${escapeHTML(digest.mood || '')}</p>
            <p class="digest-summary">${escapeHTML(digest.summary || '')}</p>
            ${digest.themes?.length ? `<div class="ai-tag-row">${digest.themes.map((theme) => `<button type="button" class="ai-tag" data-topic="${escapeHTML(theme.name)}">#${escapeHTML(theme.name)}</button>`).join('')}</div>` : ''}
            ${(digest.highlights || []).length ? `<div class="digest-highlights"><span class="section-label">Notable lines</span>${digest.highlights.map((line) => `<p>${escapeHTML(line)}</p>`).join('')}</div>` : ''}
            ${digest.questions?.length ? `<div class="digest-questions"><span class="section-label">Open questions</span>${digest.questions.map((question) => `<p>${escapeHTML(question)}</p>`).join('')}</div>` : ''}
            <div class="digest-stats">
                <span><strong>${digest.stats?.posts ?? 0}</strong> thoughts</span>
                <span><strong>${digest.stats?.voices ?? 0}</strong> voices</span>
                <span><strong>${digest.stats?.words ?? 0}</strong> words</span>
            </div>`;
        if (banner && banner === target) banner.hidden = false;
    }

    async function loadThreadSummary() {
        const box = $('#threadSummary');
        if (!box || !state.threadPostId) return;
        box.hidden = false;
        box.innerHTML = '<div class="ai-loading"><span class="ai-orb is-thinking">✦</span><div><strong>Summarising the thread…</strong></div></div>';
        const { response, payload } = await apiPost('/api/ai/summary/', { post_id: state.threadPostId });
        if (!response.ok) {
            box.innerHTML = '<div class="ai-error">Could not summarise this thread.</div>';
            return;
        }
        box.innerHTML = `
            <div class="digest-head"><span class="section-label">Thread summary</span><span class="ai-chip">assistant</span></div>
            <p class="digest-summary">${escapeHTML(payload.summary || '')}</p>
            ${payload.keywords?.length ? `<div class="ai-tag-row">${payload.keywords.map((word) => `<span class="ai-keyword">${escapeHTML(word)}</span>`).join('')}</div>` : ''}`;
    }

    async function suggestRepliesFor(card) {
        const container = card.querySelector('.ai-reply-chips');
        if (!container) return;
        container.hidden = false;
        container.innerHTML = '<span class="chip-loading">Thinking…</span>';
        const { response, payload } = await apiPost('/api/ai/reply/', { post_id: card.dataset.postId });
        if (!response.ok || !payload.suggestions?.length) {
            container.innerHTML = '<span class="chip-loading">No ideas right now.</span>';
            return;
        }
        container.innerHTML = payload.suggestions.map((suggestion) => `
            <button type="button" class="ai-reply-chip" data-ai-reply-text="${escapeHTML(suggestion.text)}" title="${escapeHTML(suggestion.label)}">
                ${escapeHTML(suggestion.text.length > 96 ? `${suggestion.text.slice(0, 96)}…` : suggestion.text)}
            </button>`).join('');
    }

    // --------------------------------------------------------------------- //
    // Inline replies
    // --------------------------------------------------------------------- //
    function openInlineReply(card) {
        const box = card.querySelector('.inline-reply');
        if (!box) return;
        box.hidden = false;
        state.activeCard = card;
        const input = box.querySelector('.inline-reply-input');
        input?.focus();
        if (aiRepliesEnabled() && !box.querySelector('.ai-reply-chips')?.children.length) {
            suggestRepliesFor(card);
        }
    }

    async function sendInlineReply(card) {
        const input = card.querySelector('.inline-reply-input');
        const button = card.querySelector('.btn-send-reply');
        const body = input?.value.trim();
        if (!body) return;
        button.disabled = true;
        const { response, payload } = await apiPost(`/api/posts/${encodeURIComponent(card.dataset.postId)}/reply/`, { body });
        button.disabled = false;
        if (!response.ok || !payload.reply) {
            showToast(payload.error || 'Could not send that reply.', 'warn');
            return;
        }
        input.value = '';
        card.querySelector('.inline-reply').hidden = true;
        input.blur();
        applyPostState(card, payload.post);
        const list = card.closest('.thread-replies') || $('#threadReplies');
        if (list) {
            list.appendChild(renderPost(payload.reply));
            $$('.empty-state', list).forEach((element) => element.remove());
        }
        showToast('Reply added.');
    }

    // --------------------------------------------------------------------- //
    // Post actions
    // --------------------------------------------------------------------- //
    async function syncPostAction(card, actionType) {
        const { response, payload } = await apiPost(`/api/posts/${encodeURIComponent(card.dataset.postId)}/${actionType}/`);
        if (!response.ok || !payload.post) throw new Error(payload.error || 'Could not save that');
        applyPostState(card, payload.post);
        return payload;
    }

    async function toggleFollow(handle, button) {
        const { response, payload } = await apiPost(`/api/profiles/${encodeURIComponent(handle)}/follow/`);
        if (!response.ok || typeof payload.following !== 'boolean') {
            throw new Error(payload.error || 'Could not update follow status');
        }
        const following = payload.following;
        $$(`[data-follow-button][data-handle="${CSS.escape(handle)}"]`).forEach((element) => {
            element.classList.toggle('is-following', following);
            element.textContent = following ? 'Following' : 'Follow';
            element.setAttribute('aria-pressed', following ? 'true' : 'false');
        });
        const followerCount = $('#profileFollowersCount');
        if (followerCount) {
            const current = parseInt(followerCount.textContent.replace(/[^0-9]/g, ''), 10) || 0;
            followerCount.textContent = number(Math.max(0, current + (following ? 1 : -1)));
        }
        $$('.post-card').forEach((card) => {
            if (card.dataset.handle === handle) {
                card.dataset.following = following ? 'true' : 'false';
                card.querySelector('[data-follow-badge]')?.toggleAttribute('hidden', !following);
            }
        });
        return following;
    }

    function startEditPost(card) {
        const body = card.querySelector('.post-text');
        if (!body || card.querySelector('.post-edit-area')) return;
        const original = card.dataset.searchable || '';
        const current = body.textContent;
        const editor = document.createElement('div');
        editor.className = 'post-edit-area';
        editor.innerHTML = `
            <textarea class="post-edit-input" maxlength="${MAX_LENGTH}" rows="3">${escapeHTML(current)}</textarea>
            <div class="post-edit-actions">
                <span class="post-edit-count">${current.length}/${MAX_LENGTH}</span>
                <button type="button" class="btn-ghost small" data-cancel-edit>Cancel</button>
                <button type="button" class="btn-primary small" data-save-edit>Save changes</button>
            </div>`;
        body.replaceWith(editor);
        const input = editor.querySelector('.post-edit-input');
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        input.addEventListener('input', () => {
            editor.querySelector('.post-edit-count').textContent = `${input.value.length}/${MAX_LENGTH}`;
        });
        editor.addEventListener('click', async (event) => {
            if (event.target.closest('[data-cancel-edit]')) {
                const paragraph = document.createElement('p');
                paragraph.className = 'post-text';
                paragraph.innerHTML = linkify(current);
                editor.replaceWith(paragraph);
                return;
            }
            if (event.target.closest('[data-save-edit]')) {
                const value = input.value.trim();
                if (!value) {
                    showToast('A thought cannot be empty.', 'warn');
                    return;
                }
                const { response, payload } = await apiPost(`/api/posts/${encodeURIComponent(card.dataset.postId)}/edit/`, { body: value });
                if (!response.ok || !payload.post) {
                    showToast(payload.error || 'Could not save changes.', 'warn');
                    return;
                }
                const paragraph = document.createElement('p');
                paragraph.className = 'post-text';
                paragraph.innerHTML = linkify(payload.post.body);
                editor.replaceWith(paragraph);
                applyPostState(card, payload.post);
                card.dataset.searchable = `${payload.post.author_name} ${payload.post.handle} ${payload.post.body}`;
                showToast('Thought updated.');
                void original;
            }
        });
    }

    function copyToClipboard(text, successMessage = 'Copied to clipboard.') {
        const share = () => {
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text)
                    .then(() => showToast(successMessage))
                    .catch(() => showToast('Copy failed — select the text manually.', 'warn'));
            } else {
                const area = document.createElement('textarea');
                area.value = text;
                area.style.position = 'fixed';
                area.style.opacity = '0';
                document.body.appendChild(area);
                area.select();
                try {
                    document.execCommand('copy');
                    showToast(successMessage);
                } catch (error) {
                    showToast('Copy failed — select the text manually.', 'warn');
                }
                area.remove();
            }
        };
        share();
    }

    async function deletePost(card, button) {
        const wanted = await askConfirm({
            title: 'Delete this thought?',
            body: 'It will disappear for everyone, and this cannot be undone.',
            accept: 'Delete thought',
        });
        if (!wanted) {
            button.disabled = false;
            return;
        }
        button.disabled = true;
        const { response, payload } = await apiPost(`/api/posts/${encodeURIComponent(card.dataset.postId)}/delete/`);
        if (!response.ok || !payload.deleted) {
            button.disabled = false;
            showToast(payload.error || 'Could not delete that thought.', 'warn');
            return;
        }
        card.style.transition = 'opacity .25s ease, transform .25s ease';
        card.style.opacity = '0';
        card.style.transform = 'scale(.97)';
        window.setTimeout(() => {
            const container = card.parentElement;
            card.remove();
            state.offset = Math.max(0, state.offset - 1);
            if (container && !container.querySelector('.post-card') && !container.querySelector('.empty-state')) {
                container.insertAdjacentHTML('beforeend', '<div class="empty-state">Nothing here yet.</div>');
            }
        }, 240);
        showToast('Thought deleted.');
    }

    async function showRelated(card) {
        // Open the drawer in a loading state — no wasted assistant request.
        openAI('related', '', { run: false });
        if (!aiStream) return;
        state.aiText = '';
        $('#aiContext')?.setAttribute('hidden', '');
        aiLoading('Finding related thoughts…', 'Comparing this thought with the rest of the space.');
        const { response, payload } = await apiGet(`/api/posts/${encodeURIComponent(card.dataset.postId)}/`);
        if (!response.ok || !payload.related) {
            aiStream.innerHTML = '<div class="ai-error">No related thoughts found.</div>';
            return;
        }
        if (!payload.related.length) {
            aiStream.innerHTML = '<div class="ai-empty"><p>Nothing similar in the space yet — this thought is the first of its kind.</p></div>';
            return;
        }
        aiStream.innerHTML = `
            <p class="ai-summary">Thoughts that share ideas with this one.</p>
            <div class="related-list">${payload.related.map((item) => `
                <a class="related-row" href="${escapeHTML(item.permalink)}">
                    <strong>@${escapeHTML(item.handle)}</strong>
                    <p>${escapeHTML(item.excerpt)}</p>
                    <span>${escapeHTML(item.published_label)}</span>
                </a>`).join('')}</div>`;
    }

    // --------------------------------------------------------------------- //
    // Search
    // --------------------------------------------------------------------- //
    const searchLayer = layers.search;
    const searchInput = $('#searchInput');
    const searchHint = $('#searchHint');
    const searchResults = $('#searchResults');
    const searchInsight = $('#searchInsight');
    let searchTimer;

    function openSearch(value = '') {
        if (!searchLayer) return;
        openLayer(searchLayer, 'search');
        if (searchInput) {
            searchInput.value = value;
            searchInput.focus();
            searchInput.setSelectionRange(value.length, value.length);
        }
        if (value) runSearch(value);
    }
    const closeSearch = () => closeLayer(searchLayer, 'search');

    async function runSearch(query) {
        if (!searchResults) return;
        const term = query.trim();
        if (!term) {
            searchResults.innerHTML = `
                <div class="search-suggestions">
                    <span class="section-label">Try</span>
                    <div class="ai-tag-row">
                        <button type="button" class="ai-tag" data-search-suggestion="design">#design</button>
                        <button type="button" class="ai-tag" data-search-suggestion="philosophy">#philosophy</button>
                        <button type="button" class="ai-tag" data-search-suggestion="writing">#writing</button>
                        <button type="button" class="ai-tag" data-search-suggestion="focus">#focus</button>
                    </div>
                </div>`;
            if (searchInsight) searchInsight.hidden = true;
            if (searchHint) searchHint.textContent = 'Search thoughts, people and topics in real time.';
            return;
        }
        searchResults.innerHTML = '<div class="empty-state">Searching…</div>';
        const { response, payload } = await apiGet(`/api/search/?q=${encodeURIComponent(term)}&limit=20`);
        if (!response.ok) {
            searchResults.innerHTML = '<div class="empty-state">Search is unavailable right now.</div>';
            return;
        }
        if (searchHint) searchHint.textContent = `Results for “${term}”`;
        if (searchInsight) {
            searchInsight.hidden = !payload.insights?.summary;
            searchInsight.innerHTML = payload.insights?.summary ? `<span class="ai-chip">assistant</span> ${escapeHTML(payload.insights.summary)}` : '';
        }
        const sections = [];
        if (payload.people?.length) {
            sections.push(`
                <div class="search-section">
                    <span class="section-label">People</span>
                    <div class="people-list">${payload.people.map((person) => `
                        <div class="person-row" data-person-handle="${escapeHTML(person.handle)}">
                            <a href="/u/${encodeURIComponent(person.handle)}/" class="person-avatar-link">
                                ${avatarHTML({ avatarUrl: person.avatar_url, initial: person.avatar_initial, tone: person.avatar_tone, size: 'avatar-medium', name: person.display_name })}
                            </a>
                            <div class="person-copy">
                                <a href="/u/${encodeURIComponent(person.handle)}/"><strong>${escapeHTML(person.display_name)}</strong></a>
                                <span>@${escapeHTML(person.handle)}</span>
                                ${person.bio ? `<em>${escapeHTML(person.bio)}</em>` : ''}
                            </div>
                            <button class="follow-button person-follow${person.following ? ' is-following' : ''}" type="button" data-follow-button data-handle="${escapeHTML(person.handle)}">${person.following ? 'Following' : 'Follow'}</button>
                        </div>`).join('')}</div>
                </div>`);
        }
        if (payload.topics?.length) {
            sections.push(`
                <div class="search-section">
                    <span class="section-label">Topics</span>
                    <div class="ai-tag-row">${payload.topics.map((topic) => `<button type="button" class="ai-tag" data-topic="${escapeHTML(topic.name)}">#${escapeHTML(topic.name)} <small>${escapeHTML(topic.meta)}</small></button>`).join('')}</div>
                </div>`);
        }
        if (payload.posts?.length) {
            sections.push(`<div class="search-section"><span class="section-label">Thoughts</span><div class="search-posts" id="searchPosts"></div></div>`);
        }
        searchResults.innerHTML = sections.join('') || `<div class="empty-state">Nothing matched “${escapeHTML(term)}”. Try another keyword.</div>`;
        const container = $('#searchPosts');
        if (container) payload.posts.forEach((post) => container.appendChild(renderPost(post)));
        if (!payload.posts?.length && (payload.people?.length || payload.topics?.length)) {
            searchResults.insertAdjacentHTML('beforeend', `<div class="empty-state">No thoughts matched “${escapeHTML(term)}” yet.</div>`);
        }
    }

    // --------------------------------------------------------------------- //
    // People modal & suggestions
    // --------------------------------------------------------------------- //
    const peopleModal = layers.people;
    const peopleBody = $('#peopleModalBody');
    const peopleTitle = $('#peopleModalTitle');
    const peopleCount = $('#peopleModalCount');

    function personRow(person) {
        return `
            <div class="person-row" data-person-handle="${escapeHTML(person.handle)}">
                <a href="/u/${encodeURIComponent(person.handle)}/" class="person-avatar-link">
                    ${avatarHTML({ avatarUrl: person.avatar_url, initial: person.avatar_initial, tone: person.avatar_tone, size: 'avatar-medium', name: person.display_name })}
                </a>
                <div class="person-copy">
                    <a href="/u/${encodeURIComponent(person.handle)}/"><strong>${escapeHTML(person.display_name)}</strong></a>
                    <span>@${escapeHTML(person.handle)}</span>
                    ${person.bio ? `<em>${escapeHTML(person.bio)}</em>` : person.reason ? `<em>${escapeHTML(person.reason)}</em>` : ''}
                </div>
                <button class="follow-button person-follow${person.following ? ' is-following' : ''}" type="button" data-follow-button data-handle="${escapeHTML(person.handle)}" aria-pressed="${person.following ? 'true' : 'false'}">${person.following ? 'Following' : 'Follow'}</button>
            </div>`;
    }

    async function openPeople(mode = 'followers', handle = null) {
        if (!peopleModal || !peopleBody) return;
        const target = handle || state.profileHandle;
        if (!target) return;
        openLayer(peopleModal, 'people');
        if (peopleTitle) peopleTitle.textContent = mode === 'following' ? `@${target} follows` : `Followers of @${target}`;
        if (peopleCount) peopleCount.textContent = '';
        peopleBody.innerHTML = '<div class="empty-state">Loading…</div>';
        const { response, payload } = await apiGet(`/api/profiles/${encodeURIComponent(target)}/${mode}/`);
        if (!response.ok || !payload.people?.length) {
            peopleBody.innerHTML = `<div class="empty-state">${mode === 'following' ? 'Not following anyone yet.' : 'No followers yet.'}</div>`;
            return;
        }
        if (peopleCount) peopleCount.textContent = `${payload.count}`;
        peopleBody.innerHTML = payload.people.map(personRow).join('');
    }

    async function openSuggestions() {
        if (!peopleModal || !peopleBody) return;
        openLayer(peopleModal, 'people');
        if (peopleTitle) peopleTitle.textContent = 'Voices to follow';
        peopleBody.innerHTML = '<div class="empty-state">Finding voices…</div>';
        const { response, payload } = await apiGet('/api/suggestions/?limit=12');
        if (!response.ok || !payload.people?.length) {
            peopleBody.innerHTML = '<div class="empty-state">No suggestions right now.</div>';
            return;
        }
        if (peopleCount) peopleCount.textContent = `${payload.people.length}`;
        peopleBody.innerHTML = payload.people.map(personRow).join('');
    }

    const topicsModal = layers.topics;
    async function openTopics() {
        if (!topicsModal) return;
        const body = $('#topicsModalBody');
        openLayer(topicsModal, 'topics');
        if (!body) return;
        body.innerHTML = '<div class="empty-state">Loading topics…</div>';
        const { response, payload } = await apiGet('/api/topics/?limit=24');
        if (!response.ok || !payload.topics?.length) {
            body.innerHTML = '<div class="empty-state">Topics will appear as thoughts are published.</div>';
            return;
        }
        body.innerHTML = `<div class="topic-grid">${payload.topics.map((topic) => `
            <button type="button" class="topic-card" data-topic="${escapeHTML(topic.name)}">
                <span class="topic-rank">${escapeHTML(topic.rank)}</span>
                <strong>#${escapeHTML(topic.name)}</strong>
                <small>${escapeHTML(topic.category)} · ${escapeHTML(topic.meta)}</small>
                ${topic.sample ? `<em>${escapeHTML(topic.sample)}</em>` : ''}
                <span class="topic-momentum is-${escapeHTML(topic.momentum || 'steady')}">${escapeHTML(topic.momentum || 'steady')}</span>
            </button>`).join('')}</div>`;
    }

    // --------------------------------------------------------------------- //
    // Profile tabs
    // --------------------------------------------------------------------- //
    async function loadProfileTab(tabName, append = false) {
        if (!feedList || !state.profileHandle) return;
        state.tab = tabName;
        $$('[data-profile-tab]').forEach((tab) => {
            const active = tab.dataset.profileTab === tabName;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (!append) showSkeletons(2);
        const offset = append ? state.offset : 0;
        const { response, payload } = await apiGet(`/api/profiles/${encodeURIComponent(state.profileHandle)}/posts/?tab=${encodeURIComponent(tabName)}&limit=30&offset=${offset}`);
        if (!response.ok) {
            setFeedEmpty('Could not load these thoughts.');
            return;
        }
        if (!append) feedList.innerHTML = '';
        if (payload.posts?.length) {
            payload.posts.forEach((post) => feedList.appendChild(renderPost(post)));
            $$('.empty-state', feedList).forEach((element) => element.remove());
        } else if (!append) {
            const messages = {
                thoughts: 'No thoughts published yet.',
                replies: 'No replies yet.',
                media: 'No photos shared yet.',
                likes: 'No liked thoughts yet.',
            };
            setFeedEmpty(messages[tabName] || 'Nothing here yet.');
        }
        state.offset = payload.next_offset ?? offset + (payload.posts?.length || 0);
        state.hasMore = Boolean(payload.has_more);
        if (loadMoreButton) loadMoreButton.hidden = !state.hasMore;
        refreshTimes();
    }

    // --------------------------------------------------------------------- //
    // Settings, profile picture & account
    // --------------------------------------------------------------------- //
    function openSettings() {
        openLayer(layers.settings, 'settings');
        applyPreferences();
    }
    const closeSettings = () => closeLayer(layers.settings, 'settings');

    function updateProfileCounters() {
        const displayInput = $('#editDisplayNameInput');
        const bioInput = $('#editBioInput');
        const displayCount = $('#displayNameCount');
        const bioCounter = $('#bioCount');
        if (displayInput && displayCount) displayCount.textContent = `${displayInput.value.length}/50`;
        if (bioInput && bioCounter) bioCounter.textContent = `${bioInput.value.length}/160`;
    }

    function openProfileSettings() {
        if (!state.authenticated) {
            openAuth('login');
            showToast('Sign in to edit your profile.');
            return;
        }
        openLayer(layers.profile, 'profile');
        updateProfileCounters();
        state.pendingAvatar = '';
        state.removeAvatar = false;
        const uploadLabel = $('#avatarUploadLabel');
        if (uploadLabel) uploadLabel.textContent = 'Upload photo';
        $('#profileSettingsError')?.setAttribute('hidden', '');
        $('#profileSettingsSuccess')?.setAttribute('hidden', '');
    }
    const closeProfileSettings = () => closeLayer(layers.profile, 'profile');

    function setAvatarPreview(dataUrl) {
        const preview = $('#editAvatarPreview');
        if (!preview) return;
        preview.classList.add('has-photo');
        preview.dataset.initials = preview.textContent.trim();
        preview.innerHTML = `<img src="${dataUrl}" alt="Profile picture preview">`;
    }

    async function handleAvatarFile(file) {
        if (!file) return;
        if (file.size > 4 * 1024 * 1024) {
            showToast('Choose an image smaller than 4 MB.', 'warn');
            return;
        }
        try {
            const { dataUrl, width, height } = await fileToDataUrl(file, { square: true, max: 640, quality: 0.9 });
            state.pendingAvatar = dataUrl;
            state.removeAvatar = false;
            setAvatarPreview(dataUrl);
            const uploadLabel = $('#avatarUploadLabel');
            if (uploadLabel) uploadLabel.textContent = `Photo ready (${width}×${height}) — save to apply`;
            $('#btnRemoveAvatar')?.removeAttribute('hidden');
            showToast('Profile picture ready — press Save.');
        } catch (error) {
            showToast(error.message || 'Could not read that image.', 'warn');
        }
    }

    function applyProfileToUI(profile) {
        $$('[data-viewer-name]').forEach((element) => { element.textContent = profile.display_name; });
        const handleLabels = $$('[data-viewer-handle]');
        handleLabels.forEach((element) => { element.textContent = `@${profile.handle}`; });
        const bioTargets = $$('[data-viewer-bio]');
        bioTargets.forEach((element) => { element.textContent = profile.bio || ''; });
        refreshViewerAvatars(profile.avatar_url, profile.avatar_tone);

        const hero = $('#profileHeroAvatar');
        if (hero) {
            hero.className = `avatar avatar-hero tone-${profile.avatar_tone}${profile.avatar_url ? ' has-photo' : ''}`;
            hero.innerHTML = profile.avatar_url
                ? `<img src="${profile.avatar_url}" alt="${escapeHTML(profile.display_name)}">`
                : escapeHTML(profile.avatar_initial || 'أ');
        }
        const fullName = $('#profileFullname');
        if (fullName) fullName.textContent = profile.display_name;
        const handleDisplay = $('#profileHandleDisplay');
        if (handleDisplay) handleDisplay.textContent = `@${profile.handle}`;
        const bioDisplay = $('#profileBioDisplay');
        if (bioDisplay) bioDisplay.textContent = profile.bio || 'No bio yet.';
        const cover = document.querySelector('.profile-cover-banner');
        if (cover) cover.className = `profile-cover-banner tone-bg-${profile.avatar_tone}${profile.avatar_url ? ' has-photo-cover' : ''}`;
        const topName = document.querySelector('.profile-top-name');
        if (topName) topName.textContent = profile.display_name;
    }

    async function saveProfileSettings() {
        const button = $('#btnSaveProfileSettings');
        const errorBox = $('#profileSettingsError');
        const successBox = $('#profileSettingsSuccess');
        const displayName = $('#editDisplayNameInput')?.value.trim() || '';
        const bio = $('#editBioInput')?.value.trim() || '';
        const tone = $('#editAvatarToneInput')?.value.trim() || 'violet';
        const handle = $('#editHandleInput')?.value.trim().toLowerCase().replace(/^@+/, '') || '';
        const location = $('#editLocationInput')?.value.trim() || '';
        const website = $('#editWebsiteInput')?.value.trim() || '';

        if (!displayName) {
            if (errorBox) {
                errorBox.textContent = 'Display Name cannot be empty.';
                errorBox.hidden = false;
            }
            return;
        }

        if (button) {
            button.disabled = true;
            button.textContent = 'Saving…';
        }
        errorBox?.setAttribute('hidden', '');
        successBox?.setAttribute('hidden', '');

        const payload = {
            display_name: displayName,
            bio,
            avatar_tone: tone,
            handle,
            location,
            website,
        };
        if (state.pendingAvatar) payload.avatar_data = state.pendingAvatar;
        if (state.removeAvatar) payload.remove_avatar = true;

        const { response, payload: result } = await apiPost('/api/auth/update_profile/', payload);
        if (button) {
            button.disabled = false;
            button.textContent = 'Save';
        }
        if (!response.ok || !result.ok) {
            if (errorBox) {
                errorBox.textContent = result.error || 'Could not save your profile.';
                errorBox.hidden = false;
            }
            return;
        }

        const previousHandle = state.viewerHandle;
        state.viewerHandle = result.profile.handle;
        state.pendingAvatar = '';
        state.removeAvatar = false;
        $('#btnRemoveAvatar')?.setAttribute('hidden', '');
        const uploadLabel = $('#avatarUploadLabel');
        if (uploadLabel) uploadLabel.textContent = 'Upload photo';

        applyProfileToUI(result.profile);
        if (previousHandle && previousHandle !== result.profile.handle) {
            $$('a[href*="/u/"').forEach((anchor) => {
                if (anchor.getAttribute('href')?.startsWith(`/u/${previousHandle}/`)) {
                    anchor.setAttribute('href', `/u/${result.profile.handle}/`);
                }
            });
            $$('[data-viewer-handle]').forEach((element) => { element.textContent = `@${result.profile.handle}`; });
            $$('.person-row[data-person-handle]').forEach((row) => {
                if (row.dataset.personHandle === previousHandle) row.dataset.personHandle = result.profile.handle;
            });
            showToast(`Username updated to @${result.profile.handle}.`);
        }
        if (successBox) {
            successBox.textContent = (result.messages || []).join(' · ') || 'Profile saved.';
            successBox.hidden = false;
        }
        showToast((result.messages || [])[0] || 'Profile updated.');
        window.setTimeout(closeProfileSettings, 700);
    }

    window.setInterval(refreshTimes, 60000);

    // --------------------------------------------------------------------- //
    // Auth
    // --------------------------------------------------------------------- //
    const authLayer = layers.auth;
    const authForm = $('#authForm');
    const authError = $('#authError');
    const authSubmit = $('#authSubmit');
    let authMode = 'login';
    let pendingSignupAvatar = '';

    function setAuthMode(mode = 'login') {
        authMode = mode;
        const register = mode === 'register';
        const displayField = $('.auth-display-field');
        const avatarField = $('.auth-avatar-field');
        const usernameHint = $('.auth-username-hint');
        if (displayField) displayField.hidden = !register;
        if (avatarField) avatarField.hidden = !register;
        if (usernameHint) usernameHint.hidden = !register;
        const title = $('#authTitle');
        if (title) title.textContent = register ? 'Create your account' : 'Welcome back.';
        if (authSubmit) {
            authSubmit.innerHTML = register ? 'Create Account <span>↗</span>' : 'Sign In <span>↗</span>';
        }
        $$('[data-auth-tab]').forEach((tab) => {
            const active = tab.dataset.authTab === mode;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        authError?.setAttribute('hidden', '');
    }

    function openAuth(mode = 'login') {
        if (!authLayer) return;
        setAuthMode(mode);
        openLayer(authLayer, 'auth');
        window.setTimeout(() => {
            (mode === 'register' ? $('#authDisplayName') : $('#authUsername'))?.focus();
        }, 40);
    }
    const closeAuth = () => closeLayer(authLayer, 'auth');

    // --------------------------------------------------------------------- //
    // Global interactions
    // --------------------------------------------------------------------- //
    document.addEventListener('pointerdown', (event) => {
        const target = event.target.closest('.post-action, .side-nav-item, .side-nav-cta, .mobile-nav-item, .mobile-nav-compose, .header-cta, .publish-button, .follow-button, .feed-view-button, .tool-button, .btn-ai, .btn-primary');
        if (target) createRipple(target, event);
    });

    document.addEventListener('click', async (event) => {
        const target = event.target;

        // --- confirmation dialog ---------------------------------------- //
        if (target.closest('[data-confirm-accept]')) {
            event.preventDefault();
            settleConfirm(true);
            return;
        }
        if (target.closest('[data-confirm-cancel]')) {
            event.preventDefault();
            settleConfirm(false);
            return;
        }

        // --- composer --------------------------------------------------- //
        if (target.closest('[data-open-composer]')) {
            event.preventDefault();
            if (!state.authenticated) {
                openAuth('register');
                showToast('Create an account to share your thoughts.');
                return;
            }
            resetComposerMode();
            scrollToComposer();
            return;
        }

        if (target.closest('[data-toggle-emoji]')) {
            event.preventDefault();
            emojiPicker?.toggleAttribute('hidden');
            return;
        }
        if (target.classList.contains('emoji-option')) {
            event.preventDefault();
            if (postInput) {
                const start = postInput.selectionStart ?? postInput.value.length;
                const end = postInput.selectionEnd ?? start;
                postInput.value = `${postInput.value.slice(0, start)}${target.textContent}${postInput.value.slice(end)}`;
                postInput.focus();
                postInput.setSelectionRange(start + target.textContent.length, start + target.textContent.length);
                postInput.dispatchEvent(new Event('input'));
            }
            emojiPicker?.setAttribute('hidden', '');
            return;
        }
        if (target.closest('[data-insert-link]')) {
            event.preventDefault();
            if (postInput) {
                const start = postInput.selectionStart ?? postInput.value.length;
                const insertion = ' https://';
                postInput.value = `${postInput.value.slice(0, start)}${insertion}${postInput.value.slice(start)}`;
                postInput.focus();
                postInput.setSelectionRange(start + insertion.length, start + insertion.length);
                postInput.dispatchEvent(new Event('input'));
                showToast('Paste your link right after https://');
            }
            return;
        }
        if (target.closest('[data-remove-compose-image]')) {
            event.preventDefault();
            clearComposeImage();
            showToast('Attachment removed.');
            return;
        }

        // --- assistant -------------------------------------------------- //
        if (target.closest('[data-open-ai]')) {
            event.preventDefault();
            const trigger = target.closest('[data-open-ai]');
            openAI(trigger.dataset.aiAction || 'coach');
            return;
        }
        if (target.closest('[data-close-ai]')) {
            event.preventDefault();
            closeAI();
            return;
        }
        if (target.closest('.ai-chip-button')) {
            event.preventDefault();
            const chip = target.closest('.ai-chip-button');
            await runAIAction(chip.dataset.aiAction || 'coach');
            return;
        }
        if (target.closest('[data-ai-action]')) {
            const trigger = target.closest('[data-ai-action]');
            if (trigger.classList.contains('ai-chip-button')) return;
            event.preventDefault();
            await runAIAction(trigger.dataset.aiAction || 'coach');
            return;
        }
        if (target.closest('[data-ai-digest]')) {
            event.preventDefault();
            loadDigest();
            showToast('Reading the feed…');
            return;
        }
        if (target.closest('[data-ai-thread-summary]')) {
            event.preventDefault();
            loadThreadSummary();
            return;
        }
        if (target.closest('[data-ai-reply-suggest]')) {
            event.preventDefault();
            const card = target.closest('.post-card');
            if (card && !state.authenticated) {
                openAuth('login');
                return;
            }
            if (card) {
                state.activeCard = card;
                suggestRepliesFor(card);
            }
            return;
        }
        if (target.closest('[data-ai-reply-text]')) {
            event.preventDefault();
            const chip = target.closest('[data-ai-reply-text]');
            const card = target.closest('.post-card');
            const inlineInput = card?.querySelector('.inline-reply-input');
            if (inlineInput) {
                inlineInput.value = chip.dataset.aiReplyText;
                inlineInput.dispatchEvent(new Event('input'));
                inlineInput.focus();
                showToast('Reply idea inserted — edit it to sound like you.');
            }
            return;
        }
        if (target.closest('[data-ai-use-text]')) {
            event.preventDefault();
            const trigger = target.closest('[data-ai-use-text]');
            applyAIText(trigger.dataset.aiUseText, trigger.dataset.aiInsert);
            return;
        }
        if (target.closest('[data-ai-copy]')) {
            event.preventDefault();
            copyToClipboard(target.closest('[data-ai-copy]').dataset.aiCopy, 'Suggestion copied.');
            return;
        }
        if (target.closest('[data-ai-continue]')) {
            event.preventDefault();
            applyContinuation();
            return;
        }
        if (target.closest('[data-ai-tag]')) {
            event.preventDefault();
            const tag = target.closest('[data-ai-tag]').dataset.aiTag;
            state.suggestedTags = Array.from(new Set([...state.suggestedTags, tag])).slice(0, 4);
            if (inlineSuggest) {
                inlineSuggest.hidden = false;
                inlineSuggest.innerHTML = `<span class="section-label">Tags queued</span><div class="ai-tag-row">${state.suggestedTags.map((item) => `<span class="ai-tag is-static">#${escapeHTML(item)}</span>`).join('')}</div>`;
            }
            showToast(`#${tag} will be added when you publish.`);
            return;
        }
        if (target.closest('[data-ai-apply-tags]')) {
            event.preventDefault();
            const tags = state.aiResult?.hashtags || [];
            state.suggestedTags = Array.from(new Set([...state.suggestedTags, ...tags])).slice(0, 4);
            if (inlineSuggest) {
                inlineSuggest.hidden = false;
                inlineSuggest.innerHTML = `<span class="section-label">Tags added</span><div class="ai-tag-row">${state.suggestedTags.map((item) => `<span class="ai-tag is-static">#${escapeHTML(item)}</span>`).join('')}</div>`;
            }
            showToast('Tags queued for your post.');
            return;
        }
        if (target.closest('[data-ai-prompt]')) {
            event.preventDefault();
            const prompt = target.closest('[data-ai-prompt]').dataset.aiPrompt;
            if (!state.authenticated) {
                openAuth('register');
                return;
            }
            if (postInput) {
                postInput.value = prompt;
                postInput.dispatchEvent(new Event('input'));
            }
            resetComposerMode();
            scrollToComposer();
            return;
        }
        if (target.id === 'aiInsertButton') {
            event.preventDefault();
            const first = state.aiResult?.suggestions?.[0]?.text;
            if (first) applyAIText(first, 'composer');
            return;
        }

        // --- settings --------------------------------------------------- //
        if (target.closest('[data-open-website-settings]')) {
            event.preventDefault();
            openSettings();
            return;
        }
        if (target.closest('[data-close-website-settings]')) {
            event.preventDefault();
            closeSettings();
            return;
        }
        if (target.closest('[data-set-theme]')) {
            event.preventDefault();
            setTheme(target.closest('[data-set-theme]').dataset.setTheme);
            showToast('Ambiance updated.');
            return;
        }
        if (target.closest('[data-open-profile-settings]')) {
            event.preventDefault();
            openProfileSettings();
            return;
        }
        if (target.closest('[data-close-profile-settings]')) {
            event.preventDefault();
            closeProfileSettings();
            return;
        }
        if (target.closest('[data-open-people]')) {
            event.preventDefault();
            const trigger = target.closest('[data-open-people]');
            openPeople(trigger.dataset.mode || 'followers');
            return;
        }
        if (target.closest('[data-open-people-suggestions]')) {
            event.preventDefault();
            openSuggestions();
            return;
        }
        if (target.closest('[data-close-people]')) {
            event.preventDefault();
            closeLayer(peopleModal, 'people');
            return;
        }
        if (target.closest('[data-open-topics]')) {
            event.preventDefault();
            openTopics();
            return;
        }
        if (target.closest('[data-close-topics]')) {
            event.preventDefault();
            closeLayer(topicsModal, 'topics');
            return;
        }
        if (target.id === 'refreshTopicsButton') {
            event.preventDefault();
            openTopics();
            return;
        }
        if (target.closest('[data-tone-choice]')) {
            event.preventDefault();
            const choice = target.closest('[data-tone-choice]');
            const tone = choice.dataset.toneChoice;
            const input = $('#editAvatarToneInput');
            if (input) input.value = tone;
            $$('[data-tone-choice]').forEach((swatch) => {
                const selected = swatch === choice;
                swatch.classList.toggle('is-active', selected);
                swatch.setAttribute('aria-checked', selected ? 'true' : 'false');
            });
            const preview = $('#editAvatarPreview');
            if (preview && !state.pendingAvatar) {
                preview.className = `avatar avatar-hero tone-${tone}`;
            }
            return;
        }
        if (target.closest('#btnRemoveAvatar')) {
            event.preventDefault();
            state.pendingAvatar = '';
            state.removeAvatar = true;
            const preview = $('#editAvatarPreview');
            if (preview) {
                preview.className = `avatar avatar-hero tone-${$('#editAvatarToneInput')?.value || 'violet'}`;
                preview.innerHTML = escapeHTML(preview.dataset.initials || 'أ');
            }
            $('#btnRemoveAvatar')?.setAttribute('hidden', '');
            const uploadLabel = $('#avatarUploadLabel');
            if (uploadLabel) uploadLabel.textContent = 'Upload photo';
            showToast('Profile picture will be removed when you save.');
            return;
        }
        if (target.closest('#btnSaveProfileSettings')) {
            event.preventDefault();
            saveProfileSettings();
            return;
        }
        if (target.closest('#btnChangePassword')) {
            event.preventDefault();
            const current = $('#currentPasswordInput')?.value || '';
            const next = $('#newPasswordInput')?.value || '';
            const note = $('#passwordNote');
            const { response, payload } = await apiPost('/api/auth/change_password/', { current_password: current, new_password: next });
            if (note) {
                note.hidden = false;
                note.textContent = response.ok ? 'Password updated.' : (payload.error || 'Could not update password.');
                note.classList.toggle('is-error', !response.ok);
            }
            if (response.ok) {
                if (payload.token) setToken(payload.token);
                $('#currentPasswordInput').value = '';
                $('#newPasswordInput').value = '';
                showToast('Password updated.');
            }
            return;
        }
        if (target.closest('[data-logout]')) {
            event.preventDefault();
            const { payload } = await apiPost('/api/auth/logout/');
            setToken('');
            store.remove(DRAFT_KEY);
            state.authenticated = false;
            window.location.href = '/';
            void payload;
            return;
        }
        if (target.closest('#confirmLayer') && target.classList.contains('modal-backdrop')) {
            event.preventDefault();
            settleConfirm(false);
            return;
        }
        if (target.classList.contains('modal-backdrop') || target.classList.contains('modal-layer')) {
            [layers.settings, layers.profile, peopleModal, topicsModal].forEach((layer) => {
                if (layer && !layer.hidden) {
                    const key = layer === layers.settings ? 'settings' : layer === layers.profile ? 'profile' : layer === peopleModal ? 'people' : 'topics';
                    closeLayer(layer, key);
                }
            });
            return;
        }

        // --- auth ------------------------------------------------------- //
        if (target.closest('[data-open-auth]')) {
            event.preventDefault();
            openAuth(target.closest('[data-open-auth]').dataset.authMode || 'login');
            return;
        }
        if (target.closest('[data-close-auth]')) {
            event.preventDefault();
            closeAuth();
            return;
        }
        if (target.closest('[data-auth-tab]')) {
            event.preventDefault();
            setAuthMode(target.closest('[data-auth-tab]').dataset.authTab || 'login');
            return;
        }

        // --- search ----------------------------------------------------- //
        if (target.closest('#searchTrigger')) {
            event.preventDefault();
            openSearch();
            return;
        }
        if (target.closest('[data-close-search]')) {
            event.preventDefault();
            closeSearch();
            return;
        }
        if (target.closest('[data-search-suggestion]')) {
            event.preventDefault();
            const term = target.closest('[data-search-suggestion]').dataset.searchSuggestion;
            if (searchInput) searchInput.value = term;
            runSearch(term);
            return;
        }
        if (target.closest('[data-topic]')) {
            event.preventDefault();
            const topic = target.closest('[data-topic]').dataset.topic;
            openSearch(topic);
            return;
        }
        if (target.id === 'notFoundSearch') {
            event.preventDefault();
            openSearch(target.dataset.query || '');
            return;
        }

        // --- feed controls ---------------------------------------------- //
        if (target.closest('[data-feed-tab]')) {
            event.preventDefault();
            setTab(target.closest('[data-feed-tab]').dataset.feedTab || 'all');
            return;
        }
        if (target.closest('#sortButton')) {
            event.preventDefault();
            const menu = $('#sortMenu');
            const open = menu?.hasAttribute('hidden');
            menu?.toggleAttribute('hidden', !open);
            $('#sortButton')?.setAttribute('aria-expanded', open ? 'true' : 'false');
            return;
        }
        // NOTE: sort options use data-sort-option (not data-sort) because the
        // feed container itself carries data-sort as state — matching the
        // container here would reload the feed on every click inside it.
        if (target.closest('[data-sort-option]')) {
            event.preventDefault();
            const trigger = target.closest('[data-sort-option]');
            const labels = { latest: 'Latest', trending: 'Trending', top: 'Most liked' };
            const choice = trigger.dataset.sortOption;
            setSort(choice, labels[choice] || 'Latest');
            return;
        }
        if (!target.closest('.sort-wrap') && !$('#sortMenu')?.hasAttribute('hidden')) {
            $('#sortMenu')?.setAttribute('hidden', '');
            $('#sortButton')?.setAttribute('aria-expanded', 'false');
        }
        if (target.closest('[data-refresh-feed]')) {
            event.preventDefault();
            replayClass(target.closest('[data-refresh-feed]'), 'is-spinning', 700);
            state.offset = 0;
            await loadFeed({ quiet: true });
            showToast('Feed refreshed.');
            return;
        }
        if (target.closest('[data-nav]')) {
            event.preventDefault();
            const nav = target.closest('[data-nav]');
            const navType = nav.dataset.nav;
            $$('[data-nav]').forEach((item) => item.classList.toggle('is-active', item === nav));
            if (navType === 'bookmarks') {
                if (!state.authenticated) {
                    openAuth('login');
                    showToast('Sign in to see your saved thoughts.');
                    return;
                }
                state.query = '';
                state.topic = '';
                setTab('bookmarks');
                document.getElementById('feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
            if (navType === 'profile') {
                window.location.href = nav.getAttribute('href') || `/u/${state.viewerHandle}/`;
                return;
            }
            state.query = '';
            state.topic = '';
            state.tab = 'all';
            setTab('all');
            $('#feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
        if (target.closest('[data-profile-tab]')) {
            event.preventDefault();
            state.offset = 0;
            loadProfileTab(target.closest('[data-profile-tab]').dataset.profileTab);
            return;
        }
        if (target.id === 'loadMoreButton') {
            event.preventDefault();
            if (state.page === 'profile') loadProfileTab(state.tab, true);
            else loadFeed({ append: true });
            return;
        }

        // --- follow buttons (rails, modals, search results) ------------- //
        const followButton = target.closest('[data-follow-button]');
        if (followButton) {
            event.preventDefault();
            if (!state.authenticated) {
                openAuth('login');
                showToast('Sign in to build your circles.');
                return;
            }
            followButton.disabled = true;
            try {
                const following = await toggleFollow(followButton.dataset.handle, followButton);
                showToast(following ? 'Added to your circles.' : 'Removed from your circles.');
            } catch (error) {
                showToast(error.message || 'Could not update follow status.', 'warn');
            } finally {
                followButton.disabled = false;
            }
            return;
        }

        // --- post cards -------------------------------------------------- //
        const card = target.closest('.post-card');
        if (!card) return;

        // Inline reply controls carry no data-action, so they are resolved
        // before the action-button dispatch below (which returns early).
        if (target.closest('[data-cancel-reply]')) {
            event.preventDefault();
            const box = card.querySelector('.inline-reply');
            if (box) {
                box.hidden = true;
                card.querySelector('.inline-reply-input')?.blur();
            }
            return;
        }
        if (target.closest('.btn-send-reply')) {
            event.preventDefault();
            sendInlineReply(card);
            return;
        }

        if (target.closest('[data-post-menu]')) {
            event.preventDefault();
            const menu = card.querySelector('.post-menu');
            const button = target.closest('[data-post-menu]');
            const willOpen = menu?.hasAttribute('hidden');
            $$('.post-menu').forEach((item) => item.setAttribute('hidden', ''));
            $$('[data-post-menu]').forEach((item) => item.setAttribute('aria-expanded', 'false'));
            menu?.toggleAttribute('hidden', !willOpen);
            button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
            return;
        }
        if (target.closest('[data-action="copy-link"]')) {
            event.preventDefault();
            copyToClipboard(`${window.location.origin}${card.dataset.permalink}`, 'Link copied.');
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            return;
        }
        if (target.closest('[data-action="open-thread"]')) {
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            return;
        }
        if (target.closest('[data-action="ai-related"]')) {
            event.preventDefault();
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            showRelated(card);
            return;
        }
        if (target.closest('[data-action="report"]')) {
            event.preventDefault();
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            showToast('Thank you — this thought has been flagged for review.');
            return;
        }
        if (target.closest('[data-action="edit-post"]')) {
            event.preventDefault();
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            startEditPost(card);
            return;
        }
        if (target.closest('[data-action="delete-post"]')) {
            event.preventDefault();
            card.querySelector('.post-menu')?.setAttribute('hidden', '');
            deletePost(card, target.closest('[data-action="delete-post"]'));
            return;
        }

        const actionButton = target.closest('[data-action]');
        if (!actionButton) return;
        const actionType = actionButton.dataset.action;

        if (['like', 'repost', 'bookmark', 'reply'].includes(actionType) && !state.authenticated) {
            openAuth('login');
            showToast('Sign in to interact with thoughts.');
            return;
        }

        if (actionType === 'reply') {
            state.activeCard = card;
            openInlineReply(card);
            return;
        }
        if (actionType === 'share') {
            replayClass(actionButton, 'is-spinning', 620);
            copyToClipboard(`${window.location.origin}${card.dataset.permalink}`, 'Link copied to share.');
            return;
        }
        if (['like', 'repost', 'bookmark'].includes(actionType)) {
            const wasActive = actionButton.classList.contains('is-active');
            const countKey = actionType === 'like' ? 'likes' : actionType === 'repost' ? 'reposts' : null;
            actionButton.classList.toggle('is-active', !wasActive);
            if (countKey) {
                const count = actionButton.querySelector(`[data-count="${countKey}"]`);
                if (count) count.textContent = number((parseInt(count.textContent, 10) || 0) + (wasActive ? -1 : 1));
            }
            replayClass(actionButton, actionType === 'like' ? 'is-popping' : actionType === 'repost' ? 'is-spinning' : 'is-dropping', 620);
            actionButton.disabled = true;
            try {
                const payload = await syncPostAction(card, actionType);
                const messages = {
                    like: payload.active ? 'Added to your likes.' : 'Like removed.',
                    repost: payload.active ? 'Reposted this thought.' : 'Repost removed.',
                    bookmark: payload.active ? 'Saved to your collection.' : 'Removed from your collection.',
                };
                showToast(messages[actionType]);
            } catch (error) {
                actionButton.classList.toggle('is-active', wasActive);
                if (countKey) {
                    const count = actionButton.querySelector(`[data-count="${countKey}"]`);
                    if (count) count.textContent = number((parseInt(count.textContent, 10) || 0) + (wasActive ? 1 : -1));
                }
                showToast(error.message || 'Could not save that.', 'warn');
            } finally {
                actionButton.disabled = false;
            }
            return;
        }
    });

    // Uploads & inputs
    imageInput?.addEventListener('change', async () => {
        const file = imageInput.files?.[0];
        if (!file) return;
        if (file.size > 6 * 1024 * 1024) {
            showToast('Photos must be smaller than 6 MB.', 'warn');
            imageInput.value = '';
            return;
        }
        try {
            const { dataUrl, width, height } = await fileToDataUrl(file, { max: 1280, quality: 0.88 });
            attachComposeImage(dataUrl, { name: file.name, width, height, bytes: file.size });
        } catch (error) {
            showToast(error.message || 'Could not attach that image.', 'warn');
        }
    });

    $('#avatarFileInput')?.addEventListener('change', (event) => {
        handleAvatarFile(event.target.files?.[0]);
    });

    const dropZone = $('#avatarDropZone');
    if (dropZone) {
        ['dragenter', 'dragover'].forEach((type) => dropZone.addEventListener(type, (event) => {
            event.preventDefault();
            dropZone.classList.add('is-dragging');
        }));
        ['dragleave', 'drop'].forEach((type) => dropZone.addEventListener(type, (event) => {
            event.preventDefault();
            dropZone.classList.remove('is-dragging');
        }));
        dropZone.addEventListener('drop', (event) => {
            const file = event.dataTransfer?.files?.[0];
            handleAvatarFile(file);
        });
    }

    postInput?.addEventListener('input', () => {
        updateComposerState();
        scheduleComposeHints();
        saveDraft();
    });

    postInput?.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
            event.preventDefault();
            publishPost();
            return;
        }
        const atEnd = postInput.selectionStart === postInput.value.length && postInput.selectionEnd === postInput.value.length;
        if (event.key === 'Tab' && !event.shiftKey && !event.metaKey && !event.ctrlKey && state.continuation && atEnd) {
            event.preventDefault();
            applyContinuation();
        }
    });

    publishButton?.addEventListener('click', publishPost);

    searchInput?.addEventListener('input', () => {
        window.clearTimeout(searchTimer);
        const term = searchInput.value;
        searchTimer = window.setTimeout(() => runSearch(term), 220);
    });

    $('#toggleReducedMotion')?.addEventListener('change', (event) => {
        store.set('athar_reduced_motion', event.target.checked ? 'true' : 'false');
        document.documentElement.dataset.reducedMotion = event.target.checked ? 'true' : 'false';
        showToast(event.target.checked ? 'Calm motion enabled.' : 'Default motion restored.');
    });

    $('#toggleCompactDensity')?.addEventListener('change', (event) => {
        store.set('athar_compact_density', event.target.checked ? 'true' : 'false');
        document.documentElement.dataset.compactDensity = event.target.checked ? 'true' : 'false';
        showToast(event.target.checked ? 'Compact density enabled.' : 'Comfortable density restored.');
    });

    $('#toggleAiTags')?.addEventListener('change', (event) => {
        if (!event.target.checked) hideComposeHints();
        else scheduleComposeHints();
    });

    $('#toggleAiReplies')?.addEventListener('change', (event) => {
        store.set('athar_ai_replies', event.target.checked ? 'true' : 'false');
        showToast(event.target.checked ? 'Inline reply ideas enabled.' : 'Inline reply ideas disabled.');
    });

    $('#toggleAiTags')?.addEventListener('change', (event) => {
        store.set('athar_ai_tags', event.target.checked ? 'true' : 'false');
        showToast(event.target.checked ? 'Tag suggestions enabled.' : 'Tag suggestions disabled.');
    });

    $('#editDisplayNameInput')?.addEventListener('input', updateProfileCounters);
    $('#editBioInput')?.addEventListener('input', updateProfileCounters);

    document.addEventListener('input', (event) => {
        const inlineInput = event.target.closest?.('.inline-reply-input');
        if (inlineInput) {
            const card = inlineInput.closest('.post-card');
            const counter = card.querySelector('.inline-reply-count');
            const send = card.querySelector('.btn-send-reply');
            if (counter) counter.textContent = `${inlineInput.value.length}/${MAX_LENGTH}`;
            if (send) send.disabled = !inlineInput.value.trim();
        }
    });

    authForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        let displayName = $('#authDisplayName')?.value.trim() || '';
        let username = ($('#authUsername')?.value.trim().toLowerCase() || '').replace(/^@+/, '');
        const password = $('#authPassword')?.value || '';

        if (authMode === 'register') {
            if (!username && displayName) {
                username = displayName.toLowerCase().replace(/[^a-z0-9_.-]/g, '').slice(0, 30);
            }
            if (!displayName && username) displayName = username;
            if (username.length < 1 || username.length > 30) {
                if (authError) {
                    authError.textContent = 'Username must be between 1 and 30 characters.';
                    authError.hidden = false;
                }
                return;
            }
        } else if (!username) {
            if (authError) {
                authError.textContent = 'Please enter your username.';
                authError.hidden = false;
            }
            return;
        }

        if (password.length < 8) {
            if (authError) {
                authError.textContent = 'Password must be at least 8 characters.';
                authError.hidden = false;
            }
            return;
        }

        const body = authMode === 'register'
            ? { display_name: displayName, handle: username, password }
            : { username, password };
        if (authMode === 'register' && pendingSignupAvatar) body.avatar_data = pendingSignupAvatar;

        authSubmit.disabled = true;
        authError?.setAttribute('hidden', '');
        const { response, payload } = await apiPost(`/api/auth/${authMode}/`, body);
        authSubmit.disabled = false;
        if (!response.ok || !payload.ok) {
            if (authError) {
                authError.textContent = payload.error || 'Could not complete that request.';
                authError.hidden = false;
            }
            return;
        }
        if (payload.token) setToken(payload.token);
        showToast(authMode === 'register' ? `Welcome, @${payload.profile.handle}!` : 'Signed in.');
        window.location.href = payload.token ? `/?auth_token=${encodeURIComponent(payload.token)}` : '/';
    });

    $('#authAvatarInput')?.addEventListener('change', async (event) => {
        const file = event.target.files?.[0];
        if (!file) return;
        try {
            const { dataUrl } = await fileToDataUrl(file, { square: true, max: 640, quality: 0.9 });
            pendingSignupAvatar = dataUrl;
            const preview = $('#authAvatarPreview');
            if (preview) {
                preview.classList.add('has-photo');
                preview.innerHTML = `<img src="${dataUrl}" alt="Profile picture preview">`;
            }
            $('#authAvatarClear')?.removeAttribute('hidden');
        } catch (error) {
            showToast(error.message || 'Could not read that image.', 'warn');
        }
    });

    $('#authAvatarClear')?.addEventListener('click', () => {
        pendingSignupAvatar = '';
        const preview = $('#authAvatarPreview');
        if (preview) {
            preview.classList.remove('has-photo');
            preview.textContent = 'A';
        }
        $('#authAvatarClear')?.setAttribute('hidden', '');
    });

    // Escape / shortcuts
    document.addEventListener('keydown', (event) => {
        const active = document.activeElement;
        // A field inside a hidden layer must not count as "typing", otherwise
        // keyboard shortcuts silently stop working after a modal closes.
        const typing = Boolean(active && !active.closest?.('[hidden]') &&
            (['INPUT', 'TEXTAREA'].includes(active.tagName) || active.isContentEditable));
        const meta = event.metaKey || event.ctrlKey;

        if (event.key === 'Escape') {
            settleConfirm(false);
            closeSearch();
            closeAuth();
            closeSettings();
            closeProfileSettings();
            closeAI();
            closeLayer(peopleModal, 'people');
            closeLayer(topicsModal, 'topics');
            $$('.post-menu').forEach((menu) => menu.setAttribute('hidden', ''));
            emojiPicker?.setAttribute('hidden', '');
            return;
        }
        if (meta && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            openSearch();
            return;
        }
        if (meta && event.key === 'Enter' && document.activeElement === postInput) {
            event.preventDefault();
            publishPost();
            return;
        }
        if (meta && ['1', '2', '3', '4', '5', '6'].includes(event.key)) {
            const map = {
                1: () => { window.location.href = '/'; },
                2: () => openTopics(),
                3: () => { if (state.authenticated) setTab('bookmarks'); else openAuth('login'); },
                4: () => { window.location.href = state.authenticated ? `/u/${state.viewerHandle}/` : '/'; },
                5: () => openSettings(),
                6: () => openAI('prompts'),
            };
            event.preventDefault();
            map[event.key]();
            return;
        }
        if (!typing && !meta) {
            if (event.key === '/') {
                event.preventDefault();
                openSearch();
            } else if (event.key.toLowerCase() === 'n') {
                event.preventDefault();
                if (state.authenticated) {
                    resetComposerMode();
                    scrollToComposer();
                } else {
                    openAuth('register');
                }
            } else if (event.key.toLowerCase() === 'd') {
                event.preventDefault();
                loadDigest();
            }
        }
    });

    // --------------------------------------------------------------------- //
    // Boot
    // --------------------------------------------------------------------- //
    applyPreferences();
    updateComposerState();
    restoreDraft();
    $$('.modal-layer, .ai-layer, .search-layer, .auth-layer').forEach((layer) => {
        if (layer.hidden) layer.style.display = 'none';
    });
    refreshTimes();

    if (state.page === 'thread') {
        state.activeCard = document.querySelector(`[data-post-id="${state.threadPostId}"]`);
    }
})();
