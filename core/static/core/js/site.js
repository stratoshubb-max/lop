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

    // Stepped registration wizard + profile-photo state (elements exist on home/profile pages).
    const registerWizard = document.getElementById('registerWizard');
    const regProgressBar = document.getElementById('regProgressBar');
    const regError = document.getElementById('regError');
    const regBack = document.getElementById('regBack');
    const regNext = document.getElementById('regNext');
    const regSkipPhoto = document.getElementById('regSkipPhoto');
    const regDisplayName = document.getElementById('regDisplayName');
    const regUsername = document.getElementById('regUsername');
    const regAvailability = document.getElementById('regAvailability');
    const regPassword = document.getElementById('regPassword');
    const regPassword2 = document.getElementById('regPassword2');
    const regStrength = document.getElementById('regStrength');
    const regStrengthLabel = document.getElementById('regStrengthLabel');
    const regBio = document.getElementById('regBio');
    const regBioCount = document.getElementById('regBioCount');
    const regAvatarTone = document.getElementById('regAvatarTone');
    const regReviewName = document.getElementById('regReviewName');
    const regReviewHandle = document.getElementById('regReviewHandle');
    const regPfpFile = document.getElementById('regPfpFile');
    const regPfpImg = document.getElementById('regPfpImg');
    const regPfpFallback = document.getElementById('regPfpFallback');
    const regPfpRemove = document.getElementById('regPfpRemove');
    const regCropperEl = document.getElementById('regCropper');
    const editPfpFile = document.getElementById('editPfpFile');
    const editPfpRemove = document.getElementById('editPfpRemove');
    let regStep = 1;
    let regSubmitting = false;
    let regToneTouched = false;
    let regAvatarDataUrl = '';
    let editAvatarDataUrl = null; // null = unchanged, '' = removed, data-URL = new photo
    let availabilityTimer;
    let lastAvailability = null;
    let regCropperInstance = null;
    let editCropperInstance = null;
    const formatter = new Intl.NumberFormat('en-US', { useGrouping: false });
    let toastTimer;
    let currentTab = 'all';
    let searchTerm = '';
    let searchTimer;
    let isPublishing = false;
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    const websiteSettingsModal = document.getElementById('websiteSettingsModal');
    const toggleReducedMotion = document.getElementById('toggleReducedMotion');
    const toggleCompactDensity = document.getElementById('toggleCompactDensity');
    const profileSettingsModal = document.getElementById('profileSettingsModal');
    const profileSettingsForm = document.getElementById('profileSettingsForm');
    const btnSaveProfileSettings = document.getElementById('btnSaveProfileSettings');
    const editDisplayNameInput = document.getElementById('editDisplayNameInput');
    const editBioInput = document.getElementById('editBioInput');
    const editAvatarToneInput = document.getElementById('editAvatarToneInput');
    const editAvatarPreview = document.getElementById('editAvatarPreview');
    const displayNameCount = document.getElementById('displayNameCount');
    const bioCount = document.getElementById('bioCount');
    const profileSettingsError = document.getElementById('profileSettingsError');

    function getStoredToken() {
        try {
            return localStorage.getItem('athar_session_token') || '';
        } catch (e) {
            return '';
        }
    }

    function setStoredToken(token) {
        try {
            if (token) {
                localStorage.setItem('athar_session_token', token);
            } else {
                localStorage.removeItem('athar_session_token');
            }
        } catch (e) {}
    }

    // Auto-sync token from URL if redirected after auth
    const urlParams = new URLSearchParams(window.location.search);
    const urlAuthToken = urlParams.get('auth_token');
    if (urlAuthToken) {
        setStoredToken(urlAuthToken);
        urlParams.delete('auth_token');
        const newSearch = urlParams.toString();
        const cleanUrl = window.location.pathname + (newSearch ? `?${newSearch}` : '') + window.location.hash;
        window.history.replaceState({}, document.title, cleanUrl);
    } else if (!authStatus && getStoredToken()) {
        const token = getStoredToken();
        const separator = window.location.search ? '&' : '?';
        window.location.replace(`${window.location.pathname}${window.location.search}${separator}auth_token=${encodeURIComponent(token)}${window.location.hash}`);
    }

    function readCookie(name) {
        const prefix = `${name}=`;
        const value = document.cookie.split('; ').find(item => item.startsWith(prefix));
        return value ? decodeURIComponent(value.slice(prefix.length)) : '';
    }

    function apiHeaders() {
        const headers = {
            'Content-Type': 'application/json',
            'X-CSRFToken': readCookie('csrftoken') || csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        };
        const token = getStoredToken();
        if (token) {
            headers['X-Session-Token'] = token;
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    }

    async function parseApiResponse(response) {
        const raw = await response.text();
        if (!raw.trim()) return {};
        try {
            return JSON.parse(raw);
        } catch (error) {
            return { error: response.status === 403 ? 'Session expired, please try again.' : 'Could not connect to server.' };
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
        verified: '<span class="verified" title="Verified account"><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 2 1.3 2.3-.1.9 2.1 1.9 1.2-.5 2.2.7 2.2-1.6 1.6-.2 2.3-2.2.5L12 17l-2 .9L8.1 17l-2.2-.5-.2-2.3-1.6-1.6.7-2.2-.5-2.2 1.9-1.2.9-2.1 2.3.1L10 2Z" fill="currentColor"/><path d="m7.1 10.1 1.8 1.8 4-4" stroke="#101114" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>'
    };

    function number(value) {
        return formatter.format(Number(value) || 0);
    }

    function numericValue(value) {
        return parseInt(String(value ?? '').replace(/[^0-9-]/g, ''), 10) || 0;
    }

    function showToast(message) {
        if (!toast || !toastMessage) return;
        toastMessage.textContent = message;
        toast.classList.remove('is-visible');
        void toast.offsetWidth;
        toast.classList.add('is-visible');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2800);
    }

    function setAuthMode(mode = 'login') {
        authMode = mode;
        const register = mode === 'register';
        const title = document.getElementById('authTitle');
        const subtitle = document.getElementById('authSubtitle');
        if (title) title.textContent = register ? 'Create your account' : 'Welcome back.';
        if (subtitle) subtitle.textContent = register ? 'Three quick steps — about a minute.' : 'Sign in to continue the conversation.';
        if (authForm) authForm.hidden = register;
        if (registerWizard) registerWizard.hidden = !register;
        document.querySelectorAll('[data-auth-tab]').forEach(tab => {
            const active = tab.dataset.authTab === mode;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (authError) authError.hidden = true;
        if (regError) regError.hidden = true;
        if (register) showRegStep(1, true);
    }

    function openAuth(mode = 'login') {
        if (!authLayer) return;
        setAuthMode(mode);
        authLayer.hidden = false;
        document.body.style.overflow = 'hidden';
        window.setTimeout(() => {
            const target = mode === 'register' ? document.getElementById('regDisplayName') : document.getElementById('authUsername');
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
        showToast('Please sign in to interact with thoughts');
        return true;
    }

    function applySavedPreferences() {
        const savedTheme = localStorage.getItem('athar_theme') || 'auto';
        setTheme(savedTheme, false);

        const savedMotion = localStorage.getItem('athar_reduced_motion') === 'true';
        if (toggleReducedMotion) toggleReducedMotion.checked = savedMotion;
        document.documentElement.dataset.reducedMotion = savedMotion ? 'true' : 'false';

        const savedDensity = localStorage.getItem('athar_compact_density') === 'true';
        if (toggleCompactDensity) toggleCompactDensity.checked = savedDensity;
        document.documentElement.dataset.compactDensity = savedDensity ? 'true' : 'false';
    }

    function setTheme(theme, save = true) {
        if (save) {
            localStorage.setItem('athar_theme', theme);
        }
        let effective = theme;
        if (theme === 'auto') {
            effective = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        }
        document.documentElement.dataset.theme = effective;

        document.querySelectorAll('[data-set-theme]').forEach(card => {
            const isActive = card.dataset.setTheme === theme;
            card.classList.toggle('is-active', isActive);
            card.setAttribute('aria-checked', isActive ? 'true' : 'false');
        });
    }

    function openWebsiteSettings() {
        if (!websiteSettingsModal) return;
        websiteSettingsModal.hidden = false;
        websiteSettingsModal.classList.remove('is-hidden');
        websiteSettingsModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        applySavedPreferences();
    }

    function closeWebsiteSettings() {
        if (!websiteSettingsModal) return;
        websiteSettingsModal.hidden = true;
        websiteSettingsModal.classList.add('is-hidden');
        websiteSettingsModal.style.display = 'none';
        document.body.style.overflow = '';
    }

    function updateProfileCounters() {
        if (displayNameCount && editDisplayNameInput) {
            displayNameCount.textContent = `${editDisplayNameInput.value.length}/50`;
        }
        if (bioCount && editBioInput) {
            bioCount.textContent = `${editBioInput.value.length}/160`;
        }
    }

    function openProfileSettings() {
        if (requireAuthentication('login')) return;
        if (!profileSettingsModal) return;
        profileSettingsModal.hidden = false;
        profileSettingsModal.classList.remove('is-hidden');
        profileSettingsModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        updateProfileCounters();
        if (profileSettingsError) profileSettingsError.hidden = true;
        editAvatarDataUrl = null;
        const editCropperReset = document.getElementById('editCropper');
        if (editCropperReset) editCropperReset.hidden = true;
        if (editPfpFile) editPfpFile.value = '';
    }

    function closeProfileSettings() {
        if (!profileSettingsModal) return;
        profileSettingsModal.hidden = true;
        profileSettingsModal.classList.add('is-hidden');
        profileSettingsModal.style.display = 'none';
        document.body.style.overflow = '';
    }

    async function loadProfileTab(tabName) {
        const handle = document.body.dataset.profileHandle;
        if (!handle || !feedList) return;

        document.querySelectorAll('[data-profile-tab]').forEach(tab => {
            const isActive = tab.dataset.profileTab === tabName;
            tab.classList.toggle('is-active', isActive);
            tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });

        feedList.innerHTML = '<div class="empty-state">Loading thoughts...</div>';

        try {
            const { response, payload } = await apiRequest(`/api/profiles/${encodeURIComponent(handle)}/posts/?tab=${encodeURIComponent(tabName)}`, {
                headers: apiHeaders()
            });
            if (!response.ok) throw new Error('Failed to load thoughts');

            feedList.innerHTML = '';
            const posts = payload.posts || [];
            if (posts.length === 0) {
                const emptyMessages = {
                    thoughts: 'No thoughts published yet.',
                    replies: 'No replies yet.',
                    likes: 'No liked thoughts yet.'
                };
                feedList.innerHTML = `<div class="empty-state">${emptyMessages[tabName] || 'No thoughts here yet.'}</div>`;
                return;
            }

            posts.forEach(post => {
                feedList.appendChild(renderPost(post));
            });
        } catch (err) {
            feedList.innerHTML = `<div class="empty-state">Could not load ${tabName}.</div>`;
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

    function escapeHTML(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function avatarHTML(profile, sizeClass) {
        const image = (profile && profile.avatar_image) || '';
        if (image) {
            return `<img class="avatar ${sizeClass} avatar-photo" src="${escapeHTML(image)}" alt="">`;
        }
        return `<span class="avatar ${sizeClass} tone-${escapeHTML((profile && profile.avatar_tone) || 'lime')}">${escapeHTML((profile && profile.avatar_initial) || 'A')}</span>`;
    }

    function replaceAvatarNode(node, profile, sizeClass, nodeId) {
        if (!node) return;
        const template = document.createElement('template');
        template.innerHTML = avatarHTML(profile, sizeClass).trim();
        const replacement = template.content.firstChild;
        if (!replacement) return;
        if (nodeId) replacement.id = nodeId;
        node.replaceWith(replacement);
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
        article.dataset.isOwner = post.is_owner ? 'true' : 'false';
        article.dataset.following = post.following ? 'true' : 'false';
        article.dataset.searchable = `${post.author_name} ${post.handle} ${post.body}`;
        const moreButtonHtml = post.is_owner
            ? '<button class="more-button is-owner" type="button" data-action="delete-post" title="Delete thought" aria-label="Delete thought"><svg viewBox="0 0 24 24" fill="none"><path d="M19 7l-.8 12.1A2 2 0 0 1 16.2 21H7.8a2 2 0 0 1-2-1.9L5 7m5 4v6m4-6v6M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3M4 7h16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>'
            : '<button class="more-button" type="button" data-toast="Post options" data-requires-auth aria-label="Options"><svg viewBox="0 0 24 24" fill="none"><circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/></svg></button>';
        article.innerHTML = `
            <div class="post-header">
                <a href="/u/${encodeURIComponent(post.handle || '')}/" class="post-header-link">
                    ${avatarHTML(post, 'avatar-large')}
                </a>
                <div class="post-author">
                    <div class="author-line">
                        <a href="/u/${encodeURIComponent(post.handle || '')}/"><strong>${escapeHTML(post.author_name || 'You')}</strong></a>
                        ${post.verified ? icons.verified : ''}
                        <a href="/u/${encodeURIComponent(post.handle || '')}/"><span class="post-handle">@${escapeHTML(post.handle || 'you')}</span></a>
                    </div>
                    <div class="post-meta"><span>${escapeHTML(post.published_label || 'Just now')}</span><i></i><span>Public</span></div>
                </div>
                ${moreButtonHtml}
            </div>
            <div class="post-body">
                <p>${escapeHTML(post.body || '')}</p>
                ${tags.length ? `<div class="post-tags">${tags.map(tag => `<span>#${escapeHTML(tag)}</span>`).join('')}</div>` : ''}
            </div>
            <div class="post-actions">
                <button class="post-action action-reply" type="button" data-action="reply" aria-label="Reply">${icons.reply}<span data-count="replies">${number(post.replies)}</span></button>
                <button class="post-action action-repost${post.is_reposted ? ' is-active' : ''}" type="button" data-action="repost" aria-label="Repost">${icons.repost}<span data-count="reposts">${number(post.reposts)}</span></button>
                <button class="post-action action-like${post.is_liked ? ' is-active' : ''}" type="button" data-action="like" aria-label="Like">${icons.like}<span data-count="likes">${number(post.likes)}</span></button>
                <button class="post-action action-bookmark${post.is_bookmarked ? ' is-active' : ''}" type="button" data-action="bookmark" aria-label="Save">${icons.bookmark}</button>
                <button class="post-action action-share" type="button" data-action="share" aria-label="Share">${icons.share}</button>
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
        if (!response.ok || !payload.post) {
            if (payload.requires_auth) openAuth('login');
            throw new Error(payload.error || 'Could not save changes');
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
        if (!response.ok || typeof payload.following !== 'boolean') {
            if (payload.requires_auth) openAuth('login');
            throw new Error(payload.error || 'Could not update follow status');
        }
        const following = Boolean(payload.following);
        button.classList.toggle('is-following', following);
        button.textContent = following ? 'Following' : 'Follow';
        button.setAttribute('aria-pressed', following ? 'true' : 'false');
        replayClass(button, 'is-popping', 520);

        const profileFollowersCount = document.getElementById('profileFollowersCount');
        if (profileFollowersCount) {
            let count = parseInt(profileFollowersCount.textContent, 10) || 0;
            count = following ? count + 1 : Math.max(0, count - 1);
            profileFollowersCount.textContent = count;
        }

        feedList?.querySelectorAll('.post-card').forEach(card => {
            const postHandle = card.querySelector('.post-handle')?.textContent.trim().replace(/^@/, '');
            if (postHandle === handle) {
                card.dataset.following = following ? 'true' : 'false';
            }
        });
        updateVisibility();
        return following;
    }

    function updateVisibility() {
        if (!feedList) return;
        const cards = [...feedList.querySelectorAll('.post-card')];
        let visible = 0;
        cards.forEach(card => {
            const matchesTab = currentTab === 'all' || card.dataset.following === 'true';
            const searchable = (card.dataset.searchable || card.textContent).toLowerCase();
            const matchesSearch = !searchTerm || searchable.includes(searchTerm.toLowerCase());
            const shouldShow = matchesTab && matchesSearch;
            card.hidden = !shouldShow;
            if (shouldShow) visible += 1;
        });
        if (filteredEmpty) {
            filteredEmpty.hidden = visible > 0;
            filteredEmpty.textContent = searchTerm
                ? `No results for "${searchTerm}". Try another keyword.`
                : 'No thoughts here yet. Try the "For you" tab.';
        }
    }

    async function publishPost() {
        if (!postInput || !publishButton || isPublishing) return;
        const body = postInput.value.trim();
        if (!body) return;
        const replyTo = postInput.dataset.replyTo || '';
        isPublishing = true;
        updateComposerState();
        publishButton.textContent = replyTo ? 'Replying...' : 'Publishing...';
        try {
            const endpoint = replyTo ? `/api/posts/${encodeURIComponent(replyTo)}/reply/` : '/api/posts/';
            const { response, payload } = await apiRequest(endpoint, {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify({ body })
            });
            if (!response.ok || !payload.post) {
                if (payload.requires_auth) openAuth('login');
                throw new Error(payload.error || 'Could not save thought');
            }
            if (replyTo) {
                const target = feedList.querySelector(`[data-post-id="${CSS.escape(replyTo)}"]`);
                if (target) applyPostState(target, payload.post);
                showToast('Your reply was added to the conversation');
            } else {
                const emptyState = feedList.querySelector('.empty-state');
                if (emptyState) emptyState.remove();
                const card = renderPost(payload.post);
                feedList.prepend(card);
                currentTab = 'all';
                document.querySelectorAll('[data-feed-tab]').forEach(tab => {
                    const active = tab.dataset.feedTab === 'all';
                    tab.classList.toggle('is-active', active);
                    tab.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                updateVisibility();
                showToast('You shared a new thought');
            }
            postInput.value = '';
            delete postInput.dataset.replyTo;
            resetComposerMode();
        } catch (error) {
            showToast(error.message || 'An unexpected error occurred');
        } finally {
            isPublishing = false;
            publishButton.textContent = 'Share Thought';
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

    async function loadSearchResults(query = '', tab = '') {
        try {
            let url = `/api/posts/?q=${encodeURIComponent(query)}`;
            if (tab) url += `&tab=${encodeURIComponent(tab)}`;
            const { response, payload } = await apiRequest(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!response.ok) return;
            if (!Array.isArray(payload.posts)) throw new Error(payload.error || 'Could not load thoughts.');
            if (payload.posts.length === 0) {
                feedList.innerHTML = tab === 'bookmarks'
                    ? '<div class="empty-state">No saved thoughts yet. Click the save icon on any thought to save it here.</div>'
                    : '<div class="empty-state">No thoughts found. Be the first to leave a thought.</div>';
            } else {
                feedList.replaceChildren(...payload.posts.map(renderPost));
            }
            updateVisibility();
        } catch (error) {
            updateVisibility();
        }
    }

    function filterFromSearch() {
        if (!searchInput) return;
        searchTerm = searchInput.value.trim();
        if (searchHint) {
            searchHint.textContent = searchTerm
                ? `Showing results for "${searchTerm}"...`
                : 'Search thoughts, voices, and topics in real-time.';
        }
        updateVisibility();
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => loadSearchResults(searchTerm), 180);
    }

    function setComposerMode(isReply) {
        const label = document.querySelector('.compose-heading .section-label');
        if (label) label.textContent = isReply ? 'Your reply' : 'In your voice';
        if (postInput) postInput.placeholder = isReply ? 'Write your reply to this thought...' : 'What thought do you want to leave today?';
        if (publishButton) publishButton.textContent = isReply ? 'Send Reply' : 'Share Thought';
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

    document.addEventListener('click', event => {
        const openComposer = event.target.closest('[data-open-composer]');
        if (openComposer) {
            event.preventDefault();
            if (!requireAuthentication('register')) scrollToComposer();
            return;
        }

        const logoutTrigger = event.target.closest('[data-logout]');
        if (logoutTrigger) {
            event.preventDefault();
            (async () => {
                try {
                    await apiRequest('/api/auth/logout/', {
                        method: 'POST',
                        headers: apiHeaders(),
                        body: JSON.stringify({})
                    });
                } catch (err) {}
                setStoredToken('');
                window.location.href = '/';
            })();
            return;
        }

        const refreshTrigger = event.target.closest('.feed-view-button');
        if (refreshTrigger) {
            event.preventDefault();
            replayClass(refreshTrigger, 'is-spinning', 700);
            loadSearchResults('').then(() => showToast('Feed refreshed'));
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

        const openProfileSettingsBtn = event.target.closest('[data-open-profile-settings]');
        if (openProfileSettingsBtn) {
            event.preventDefault();
            openProfileSettings();
            return;
        }

        const closeProfileSettingsBtn = event.target.closest('[data-close-profile-settings]');
        if (closeProfileSettingsBtn) {
            event.preventDefault();
            closeProfileSettings();
            return;
        }

        if (event.target.classList.contains('modal-backdrop') || event.target.classList.contains('modal-layer')) {
            event.preventDefault();
            closeWebsiteSettings();
            closeProfileSettings();
            return;
        }

        const openWebsiteSettingsBtn = event.target.closest('[data-open-website-settings]');
        if (openWebsiteSettingsBtn) {
            event.preventDefault();
            openWebsiteSettings();
            return;
        }

        const closeWebsiteSettingsBtn = event.target.closest('[data-close-website-settings]');
        if (closeWebsiteSettingsBtn) {
            event.preventDefault();
            closeWebsiteSettings();
            return;
        }

        const themeCard = event.target.closest('[data-set-theme]');
        if (themeCard) {
            event.preventDefault();
            setTheme(themeCard.dataset.setTheme);
            showToast('Ambiance updated');
            return;
        }

        const passwordToggle = event.target.closest('[data-toggle-password]');
        if (passwordToggle) {
            event.preventDefault();
            const input = document.getElementById(passwordToggle.dataset.togglePassword || '');
            if (input) {
                const show = input.type === 'password';
                input.type = show ? 'text' : 'password';
                passwordToggle.textContent = show ? 'Hide' : 'Show';
                passwordToggle.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
            }
            return;
        }

        const regTone = event.target.closest('[data-reg-tone]');
        if (regTone) {
            event.preventDefault();
            regToneTouched = true;
            const tone = regTone.dataset.regTone;
            if (regAvatarTone) regAvatarTone.value = tone;
            document.querySelectorAll('[data-reg-tone]').forEach(swatch => {
                const isSelected = swatch === regTone;
                swatch.classList.toggle('is-active', isSelected);
                swatch.setAttribute('aria-checked', isSelected ? 'true' : 'false');
            });
            if (regPfpFallback) regPfpFallback.className = `avatar avatar-profile tone-${tone}`;
            return;
        }

        const toneChoice = event.target.closest('[data-tone-choice]');
        if (toneChoice) {
            event.preventDefault();
            const tone = toneChoice.dataset.toneChoice;
            if (editAvatarToneInput) editAvatarToneInput.value = tone;
            document.querySelectorAll('[data-tone-choice]').forEach(swatch => {
                const isSelected = swatch === toneChoice;
                swatch.classList.toggle('is-active', isSelected);
                swatch.setAttribute('aria-checked', isSelected ? 'true' : 'false');
            });
            if (editAvatarPreview) {
                editAvatarPreview.className = `avatar avatar-hero tone-${tone}`;
            }
            return;
        }

        const profileTab = event.target.closest('[data-profile-tab]');
        if (profileTab) {
            event.preventDefault();
            loadProfileTab(profileTab.dataset.profileTab);
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
            follow.textContent = wasFollowing ? 'Follow' : 'Following';
            follow.setAttribute('aria-pressed', wasFollowing ? 'false' : 'true');
            follow.disabled = true;
            toggleFollow(handle, follow, wasFollowing)
                .then(following => showToast(following ? 'Added to your circles' : 'Removed from your circles'))
                .catch(error => {
                    follow.classList.toggle('is-following', wasFollowing);
                    follow.textContent = wasFollowing ? 'Following' : 'Follow';
                    follow.setAttribute('aria-pressed', wasFollowing ? 'true' : 'false');
                    showToast(error.message || 'Could not update follow');
                })
                .finally(() => { follow.disabled = false; });
            return;
        }

        const topic = event.target.closest('[data-topic]');
        if (topic) {
            openSearch(topic.dataset.topic || '');
            return;
        }

        const deleteTrigger = event.target.closest('[data-action="delete-post"]');
        if (deleteTrigger) {
            event.preventDefault();
            const card = deleteTrigger.closest('.post-card');
            if (!card) return;
            if (confirm('Are you sure you want to delete this thought?')) {
                deleteTrigger.disabled = true;
                apiRequest(`/api/posts/${encodeURIComponent(card.dataset.postId)}/delete/`, {
                    method: 'POST',
                    headers: apiHeaders(),
                    body: JSON.stringify({})
                }).then(({ response, payload }) => {
                    if (response.ok && payload.deleted) {
                        card.style.transition = 'all 0.25s ease-out';
                        card.style.opacity = '0';
                        card.style.transform = 'scale(0.95)';
                        window.setTimeout(() => {
                            card.remove();
                            if (feedList.querySelectorAll('.post-card').length === 0) {
                                feedList.innerHTML = '<div class="empty-state">No thoughts yet. Be the first to share one.</div>';
                            }
                        }, 250);
                        showToast('Thought deleted successfully');
                    } else {
                        showToast(payload.error || 'Could not delete thought');
                        deleteTrigger.disabled = false;
                    }
                }).catch(() => {
                    showToast('Could not delete thought');
                    deleteTrigger.disabled = false;
                });
            }
            return;
        }

        const nav = event.target.closest('[data-nav]');
        if (nav) {
            event.preventDefault();
            document.querySelectorAll('[data-nav]').forEach(item => item.classList.toggle('is-active', item === nav));
            const navType = nav.dataset.nav;
            if (navType === 'bookmarks') {
                if (requireAuthentication('login')) return;
                showToast('Your saved thoughts');
                document.getElementById('feed')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                const feedTitle = document.querySelector('.feed-heading h1');
                if (feedTitle) feedTitle.textContent = 'Saved';
                const feedDesc = document.querySelector('.feed-heading p');
                if (feedDesc) feedDesc.textContent = 'Thoughts and ideas you saved for later.';
                loadSearchResults('', 'bookmarks');
                return;
            }
            if (navType === 'home') {
                const feedTitle = document.querySelector('.feed-heading h1');
                if (feedTitle) feedTitle.textContent = 'Feed';
                const feedDesc = document.querySelector('.feed-heading p');
                if (feedDesc) feedDesc.textContent = 'Ideas from your circles, delivered quietly.';
                loadSearchResults('', '');
            }
            const destination = navType === 'discover' ? document.getElementById('discover') : navType === 'circles' ? document.getElementById('circles') : document.getElementById('feed');
            destination?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            if (navType !== 'home' && navType !== 'bookmarks') showToast(navType === 'discover' ? 'Explore what is moving now' : 'Your circles and community');
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
        if (['like', 'repost', 'bookmark', 'reply'].includes(actionType) && requireAuthentication('login')) return;
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
                    showToast(actionType === 'like' ? (active ? 'Added to your likes' : 'Like removed') : actionType === 'repost' ? (active ? 'Reposted this thought' : 'Removed repost') : (active ? 'Saved to your collection' : 'Removed from collection'));
                })
                .catch(error => {
                    action.classList.toggle('is-active', wasActive);
                    if (countKey) {
                        const count = action.querySelector(`[data-count="${countKey}"]`);
                        if (count) count.textContent = number(numericValue(count.textContent) + (wasActive ? 1 : -1));
                    }
                    showToast(error.message || 'Could not save changes');
                })
                .finally(() => { action.disabled = false; });
            return;
        }
        if (actionType === 'reply') {
            if (postInput) postInput.dataset.replyTo = card.dataset.postId;
            setComposerMode(true);
            scrollToComposer();
            showToast('Write your reply in the composer above');
            return;
        }
        if (actionType === 'share') {
            replayClass(action, 'is-spinning', 620);
            const text = card.querySelector('.post-body p')?.textContent || '';
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(() => showToast('Copied thought to clipboard')).catch(() => showToast('Thought ready to share'));
            } else {
                showToast('Thought ready to share');
            }
        }
    });

    document.getElementById('searchTrigger')?.addEventListener('click', () => openSearch());
    searchInput?.addEventListener('input', filterFromSearch);
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            closeSearch();
            closeAuth();
            closeProfileSettings();
            closeWebsiteSettings();
        }
        if ((event.metaKey || event.ctrlKey) && event.key === '5') {
            event.preventDefault();
            openWebsiteSettings();
        }
        if ((event.metaKey || event.ctrlKey) && event.key === '4') {
            const profileLink = document.querySelector('a[data-nav="profile"], .side-nav a[href^="/u/"], .mobile-nav a[href^="/u/"]');
            if (profileLink) {
                event.preventDefault();
                window.location.href = profileLink.href;
            }
        }
        if (event.key === '/' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
            event.preventDefault();
            openSearch();
        }
    });

    btnSaveProfileSettings?.addEventListener('click', async () => {
        if (!btnSaveProfileSettings) return;
        const displayName = editDisplayNameInput ? editDisplayNameInput.value.trim() : '';
        const bio = editBioInput ? editBioInput.value.trim() : '';
        const avatarTone = editAvatarToneInput ? editAvatarToneInput.value.trim() : 'violet';

        if (!displayName) {
            if (profileSettingsError) {
                profileSettingsError.textContent = 'Display Name cannot be empty.';
                profileSettingsError.hidden = false;
            }
            return;
        }

        btnSaveProfileSettings.disabled = true;
        btnSaveProfileSettings.textContent = 'Saving...';
        if (profileSettingsError) profileSettingsError.hidden = true;

        const profilePayload = {
            display_name: displayName,
            bio: bio,
            avatar_tone: avatarTone
        };
        if (editAvatarDataUrl !== null) {
            profilePayload.avatar_image = editAvatarDataUrl;
        }

        try {
            const { response, payload } = await apiRequest('/api/auth/update_profile/', {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify(profilePayload)
            });

            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || 'Failed to update profile');
            }

            const updated = payload.profile;
            const profileFullname = document.getElementById('profileFullname');
            if (profileFullname) profileFullname.textContent = updated.display_name;
            const profileTopName = document.querySelector('.profile-top-name');
            if (profileTopName) profileTopName.textContent = updated.display_name;
            const profileBioDisplay = document.getElementById('profileBioDisplay');
            if (profileBioDisplay) profileBioDisplay.textContent = updated.bio || 'No bio yet.';
            replaceAvatarNode(document.getElementById('profileHeroAvatar'), updated, 'avatar-hero', 'profileHeroAvatar');
            const coverBanner = document.querySelector('.profile-cover-banner');
            if (coverBanner) {
                coverBanner.className = `profile-cover-banner tone-bg-${updated.avatar_tone}`;
            }

            const profileMain = document.querySelector('.profile-card .profile-main');
            if (profileMain) {
                const nameElem = profileMain.querySelector('strong');
                if (nameElem) nameElem.textContent = updated.display_name;
                replaceAvatarNode(profileMain.querySelector('.avatar'), updated, 'avatar-profile', '');
            }
            replaceAvatarNode(document.querySelector('.compose-row > .avatar'), updated, 'avatar-large', '');
            const profileCardBio = document.querySelector('.profile-card .profile-bio');
            if (profileCardBio) profileCardBio.textContent = updated.bio || '';

            const editPreviewImg = document.getElementById('editAvatarPreviewImg');
            if (editPreviewImg) {
                if (updated.avatar_image) {
                    editPreviewImg.src = updated.avatar_image;
                    editPreviewImg.hidden = false;
                } else {
                    editPreviewImg.hidden = true;
                    editPreviewImg.removeAttribute('src');
                }
            }
            if (editAvatarPreview) {
                editAvatarPreview.className = `avatar avatar-hero tone-${updated.avatar_tone || 'violet'}`;
                editAvatarPreview.textContent = updated.avatar_initial || 'A';
                editAvatarPreview.hidden = Boolean(updated.avatar_image);
            }
            editAvatarDataUrl = null;

            closeProfileSettings();
            showToast('Profile updated successfully');
        } catch (error) {
            if (profileSettingsError) {
                profileSettingsError.textContent = error.message;
                profileSettingsError.hidden = false;
            }
        } finally {
            btnSaveProfileSettings.disabled = false;
            btnSaveProfileSettings.textContent = 'Save';
        }
    });

    toggleReducedMotion?.addEventListener('change', () => {
        const checked = toggleReducedMotion.checked;
        localStorage.setItem('athar_reduced_motion', checked ? 'true' : 'false');
        document.documentElement.dataset.reducedMotion = checked ? 'true' : 'false';
        showToast(checked ? 'Calm motion enabled' : 'Default motion enabled');
    });

    toggleCompactDensity?.addEventListener('change', () => {
        const checked = toggleCompactDensity.checked;
        localStorage.setItem('athar_compact_density', checked ? 'true' : 'false');
        document.documentElement.dataset.compactDensity = checked ? 'true' : 'false';
        showToast(checked ? 'Compact density enabled' : 'Comfortable density enabled');
    });

    editDisplayNameInput?.addEventListener('input', updateProfileCounters);
    editBioInput?.addEventListener('input', updateProfileCounters);

    if (websiteSettingsModal) {
        websiteSettingsModal.hidden = true;
        websiteSettingsModal.classList.add('is-hidden');
    }
    if (profileSettingsModal) {
        profileSettingsModal.hidden = true;
        profileSettingsModal.classList.add('is-hidden');
    }

    applySavedPreferences();

    authForm?.addEventListener('submit', async event => {
        event.preventDefault();
        if (!authSubmit) return;
        const username = (document.getElementById('authUsername')?.value.trim().toLowerCase() || '').replace(/^@+/, '');
        const password = document.getElementById('authPassword')?.value || '';

        if (!username) {
            if (authError) {
                authError.textContent = 'Please enter your username.';
                authError.hidden = false;
            }
            return;
        }
        if (!password || password.length < 8) {
            if (authError) {
                authError.textContent = 'Password must be at least 8 characters.';
                authError.hidden = false;
            }
            return;
        }

        authSubmit.disabled = true;
        if (authError) authError.hidden = true;
        try {
            const { response, payload: result } = await apiRequest('/api/auth/login/', {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify({ username, password })
            });
            if (!response.ok || !result.ok) throw new Error(result.error || 'Could not sign in');
            if (result.token) {
                setStoredToken(result.token);
            }
            showToast('Signed in successfully');
            const targetUrl = result.token ? `/?auth_token=${encodeURIComponent(result.token)}` : '/';
            window.location.href = targetUrl;
        } catch (error) {
            if (authError) {
                authError.textContent = error.message;
                authError.hidden = false;
            }
        } finally {
            authSubmit.disabled = false;
        }
    });

    // ------------------------------------------------------------------
    // Stepped registration wizard (Create Account in 3 steps)
    // ------------------------------------------------------------------
    const HANDLE_RE = /^[a-z0-9_.-]{1,30}$/;

    function showRegStep(step, silent = false) {
        regStep = Math.min(Math.max(step, 1), 3);
        document.querySelectorAll('[data-reg-panel]').forEach(panel => {
            panel.hidden = Number(panel.dataset.regPanel) !== regStep;
        });
        document.querySelectorAll('[data-reg-dot]').forEach(dot => {
            const n = Number(dot.dataset.regDot);
            dot.classList.toggle('is-current', n === regStep);
            dot.classList.toggle('is-done', n < regStep);
        });
        if (regProgressBar) regProgressBar.style.width = `${(regStep / 3) * 100}%`;
        if (regBack) regBack.hidden = regStep === 1;
        if (regNext) regNext.innerHTML = regStep === 3 ? 'Create Account <span>↗</span>' : 'Continue <span>→</span>';
        if (regSkipPhoto) regSkipPhoto.hidden = regStep !== 3;
        if (regError && !silent) regError.hidden = true;
        if (regStep === 3) {
            updateRegReview();
            autoSelectRegTone();
            if (regCropperInstance) regCropperInstance.refresh();
        }
        if (!silent) {
            const focusTarget = regStep === 1 ? regDisplayName : regStep === 2 ? regPassword : regBio;
            window.setTimeout(() => focusTarget?.focus(), 60);
        }
    }

    function regFail(message) {
        if (regError) {
            regError.textContent = message;
            regError.hidden = false;
        }
        return false;
    }

    function cleanRegHandle() {
        return (regUsername?.value.trim().toLowerCase() || '').replace(/^@+/, '');
    }

    function validateRegStep(step) {
        if (step === 1) {
            let handle = cleanRegHandle();
            let name = regDisplayName?.value.trim() || '';
            if (!handle && name) {
                handle = name.toLowerCase().replace(/[^a-z0-9_.-]/g, '').slice(0, 30);
                if (regUsername) regUsername.value = handle;
            }
            if (!name && handle) {
                name = handle;
                if (regDisplayName) regDisplayName.value = name;
            }
            if (name.length > 50) return regFail('Display Name cannot exceed 50 characters.');
            if (!handle) return regFail('Choose a username first — or type a display name and we’ll suggest one.');
            if (!HANDLE_RE.test(handle)) return regFail('Username: 1–30 characters (letters, numbers, _, -, .).');
            if (lastAvailability && lastAvailability.handle === handle && !lastAvailability.available) {
                return regFail(`@${handle} is already taken. Try another one.`);
            }
            return true;
        }
        if (step === 2) {
            const pw = regPassword?.value || '';
            const pw2 = regPassword2?.value || '';
            if (!pw || pw.length < 8) return regFail('Password must be at least 8 characters.');
            if (pw !== pw2) return regFail('Passwords don’t match. Try again.');
            return true;
        }
        return true;
    }

    function setAvailability(state, message) {
        if (!regAvailability) return;
        regAvailability.classList.remove('is-ok', 'is-bad');
        if (state) regAvailability.classList.add(state);
        regAvailability.textContent = message;
    }

    async function checkRegAvailability() {
        const handle = cleanRegHandle();
        if (!handle || !HANDLE_RE.test(handle)) {
            lastAvailability = null;
            setAvailability('', '1–30 characters: letters, numbers, _, -, . Must be unique.');
            return;
        }
        setAvailability('', 'Checking availability...');
        try {
            const { response, payload } = await apiRequest(`/api/auth/check_handle/?handle=${encodeURIComponent(handle)}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!response.ok) throw new Error('check failed');
            lastAvailability = { handle, available: Boolean(payload.available) };
            if (payload.available) setAvailability('is-ok', `✓ @${handle} is available`);
            else setAvailability('is-bad', `✗ @${handle} is taken — try another`);
        } catch (err) {
            setAvailability('', 'Could not check availability — you can still continue.');
        }
    }

    function updatePasswordStrength() {
        const pw = regPassword?.value || '';
        let score = 0;
        if (pw.length >= 8) score += 1;
        if (pw.length >= 12) score += 1;
        if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score += 1;
        if (/\d/.test(pw)) score += 1;
        if (/[^a-zA-Z0-9]/.test(pw)) score += 1;
        const level = pw ? Math.min(4, Math.max(1, Math.ceil(score / 1.5))) : 0;
        if (regStrength) regStrength.className = `password-strength${level ? ` strength-${level}` : ''}`;
        const labels = ['', 'Weak — add more characters', 'Fair — mix in numbers or symbols', 'Good password', 'Strong password'];
        if (regStrengthLabel) {
            regStrengthLabel.textContent = pw ? labels[level] : 'Use 8+ characters — mix letters, numbers & symbols for strength.';
        }
    }

    function updateRegReview() {
        const handle = cleanRegHandle();
        const name = regDisplayName?.value.trim() || handle || '—';
        if (regReviewName) regReviewName.textContent = name;
        if (regReviewHandle) regReviewHandle.textContent = handle ? `@${handle}` : '@—';
        if (regPfpFallback && !regAvatarDataUrl) {
            const first = Array.from(name)[0] || 'A';
            regPfpFallback.textContent = first.toUpperCase();
        }
    }

    function autoSelectRegTone() {
        if (regToneTouched || !regAvatarTone) return;
        const tones = [...document.querySelectorAll('[data-reg-tone]')].map(el => el.dataset.regTone);
        if (!tones.length) return;
        const tone = tones[cleanRegHandle().length % tones.length];
        regAvatarTone.value = tone;
        document.querySelectorAll('[data-reg-tone]').forEach(el => {
            const active = el.dataset.regTone === tone;
            el.classList.toggle('is-active', active);
            el.setAttribute('aria-checked', active ? 'true' : 'false');
        });
        if (regPfpFallback) regPfpFallback.className = `avatar avatar-profile tone-${tone}`;
    }

    async function submitRegistration(skipPhoto) {
        const handle = cleanRegHandle();
        if (!HANDLE_RE.test(handle)) {
            showRegStep(1);
            regFail('Please fix your username first.');
            return;
        }
        const pw = regPassword?.value || '';
        if (pw.length < 8 || pw !== (regPassword2?.value || '')) {
            showRegStep(2);
            regFail('Please fix your password first.');
            return;
        }
        let name = regDisplayName?.value.trim() || '';
        if (!name) name = handle;
        let avatar = skipPhoto ? '' : (regAvatarDataUrl || (regCropperInstance && regCropperInstance.isLoaded() ? regCropperInstance.exportCropped() : ''));
        const bio = (regBio?.value.trim() || '').slice(0, 160);
        const tone = regAvatarTone?.value || '';

        regSubmitting = true;
        if (regNext) {
            regNext.disabled = true;
            regNext.innerHTML = 'Creating... <span>✦</span>';
        }
        if (regError) regError.hidden = true;
        try {
            const { response, payload } = await apiRequest('/api/auth/register/', {
                method: 'POST',
                headers: apiHeaders(),
                body: JSON.stringify({ display_name: name, handle, password: pw, bio, avatar_tone: tone, avatar_image: avatar })
            });
            if (!response.ok || !payload.ok) throw new Error(payload.error || 'Could not create account');
            if (payload.token) setStoredToken(payload.token);
            showToast(`Account created! Welcome, @${handle}`);
            window.location.href = payload.token ? `/?auth_token=${encodeURIComponent(payload.token)}` : '/';
        } catch (error) {
            regFail(error.message || 'Could not create account');
            if (/taken|username/i.test(error.message || '')) showRegStep(1, true);
        } finally {
            regSubmitting = false;
            if (regNext) {
                regNext.disabled = false;
                regNext.innerHTML = 'Create Account <span>↗</span>';
            }
        }
    }

    // ------------------------------------------------------------------
    // Reusable in-browser photo cropper (drag to move, slider/wheel to zoom)
    // ------------------------------------------------------------------
    function createCropper({ stage, img, zoomInput, onCrop }) {
        const state = { scale: 1, x: 0, y: 0, base: 1, loaded: false, naturalW: 0, naturalH: 0 };
        let dragging = false;
        let lastX = 0;
        let lastY = 0;

        function stageSize() {
            return stage ? stage.clientWidth : 0;
        }

        function clampPosition() {
            const size = stageSize() || 280;
            const w = state.naturalW * state.base * state.scale;
            const h = state.naturalH * state.base * state.scale;
            state.x = Math.min(0, Math.max(size - w, state.x));
            state.y = Math.min(0, Math.max(size - h, state.y));
        }

        function render() {
            if (!state.loaded || !img) return;
            const w = state.naturalW * state.base * state.scale;
            const h = state.naturalH * state.base * state.scale;
            img.style.width = `${w}px`;
            img.style.height = `${h}px`;
            img.style.transform = `translate(${state.x}px, ${state.y}px)`;
        }

        function notify() {
            if (onCrop) onCrop(exportCropped());
        }

        function setImage(dataUrl) {
            if (!img || !stage) return;
            state.loaded = false;
            img.onload = () => {
                state.naturalW = img.naturalWidth;
                state.naturalH = img.naturalHeight;
                if (!state.naturalW || !state.naturalH) return;
                const size = stageSize() || 280;
                state.base = Math.max(size / state.naturalW, size / state.naturalH);
                state.scale = 1;
                state.x = (size - state.naturalW * state.base) / 2;
                state.y = (size - state.naturalH * state.base) / 2;
                if (zoomInput) zoomInput.value = '1';
                state.loaded = true;
                render();
                notify();
            };
            img.src = dataUrl;
        }

        function exportCropped(outputSize = 256) {
            if (!state.loaded || !img) return '';
            const size = stageSize() || 280;
            const unit = state.base * state.scale;
            if (!unit) return '';
            const sx = -state.x / unit;
            const sy = -state.y / unit;
            const sSize = size / unit;
            const canvas = document.createElement('canvas');
            canvas.width = outputSize;
            canvas.height = outputSize;
            const ctx = canvas.getContext('2d');
            if (!ctx) return '';
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, outputSize, outputSize);
            try {
                ctx.drawImage(img, sx, sy, sSize, sSize, 0, 0, outputSize, outputSize);
            } catch (err) {
                return '';
            }
            return canvas.toDataURL('image/jpeg', 0.87);
        }

        if (stage) {
            stage.addEventListener('pointerdown', event => {
                if (!state.loaded) return;
                dragging = true;
                lastX = event.clientX;
                lastY = event.clientY;
                try {
                    stage.setPointerCapture(event.pointerId);
                } catch (err) {}
                event.preventDefault();
            });
            stage.addEventListener('pointermove', event => {
                if (!dragging || !state.loaded) return;
                state.x += event.clientX - lastX;
                state.y += event.clientY - lastY;
                lastX = event.clientX;
                lastY = event.clientY;
                clampPosition();
                render();
            });
            const endDrag = () => {
                if (!dragging) return;
                dragging = false;
                notify();
            };
            stage.addEventListener('pointerup', endDrag);
            stage.addEventListener('pointercancel', endDrag);
            stage.addEventListener('wheel', event => {
                if (!state.loaded) return;
                event.preventDefault();
                const next = Math.min(3, Math.max(1, state.scale + (event.deltaY < 0 ? 0.08 : -0.08)));
                state.scale = Math.round(next * 100) / 100;
                if (zoomInput) zoomInput.value = String(state.scale);
                clampPosition();
                render();
                notify();
            }, { passive: false });
        }

        if (zoomInput) {
            zoomInput.addEventListener('input', () => {
                if (!state.loaded) return;
                state.scale = Number(zoomInput.value) || 1;
                clampPosition();
                render();
                notify();
            });
        }

        return {
            setImage,
            exportCropped,
            isLoaded: () => state.loaded,
            reset() {
                state.loaded = false;
                state.scale = 1;
                state.x = 0;
                state.y = 0;
                if (img) img.removeAttribute('src');
                if (zoomInput) zoomInput.value = '1';
            },
            refresh() {
                if (!state.loaded || !state.naturalW) return;
                const size = stageSize();
                if (!size) return;
                state.base = Math.max(size / state.naturalW, size / state.naturalH);
                clampPosition();
                render();
            }
        };
    }

    function readImageFile(file) {
        return new Promise((resolve, reject) => {
            if (!file) return reject(new Error('No file selected.'));
            if (!file.type.startsWith('image/')) return reject(new Error('Please choose an image file.'));
            if (file.size > 8 * 1024 * 1024) return reject(new Error('Image is too large (max 8MB).'));
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ''));
            reader.onerror = () => reject(new Error('Could not read that image.'));
            reader.readAsDataURL(file);
        });
    }

    // Signup-wizard cropper wiring.
    const regCropStage = document.getElementById('regCropStage');
    const regCropImg = document.getElementById('regCropImg');
    if (regCropStage && regCropImg) {
        regCropperInstance = createCropper({
            stage: regCropStage,
            img: regCropImg,
            zoomInput: document.getElementById('regCropZoom'),
            onCrop: dataUrl => {
                regAvatarDataUrl = dataUrl || '';
                if (regPfpImg) {
                    if (dataUrl) {
                        regPfpImg.src = dataUrl;
                        regPfpImg.hidden = false;
                    } else {
                        regPfpImg.hidden = true;
                    }
                }
                if (regPfpFallback) regPfpFallback.hidden = Boolean(dataUrl);
                if (regPfpRemove) regPfpRemove.hidden = !dataUrl;
            }
        });
    }

    regPfpFile?.addEventListener('change', async () => {
        const file = regPfpFile.files && regPfpFile.files[0];
        if (!file) return;
        try {
            const dataUrl = await readImageFile(file);
            if (!regCropperInstance) throw new Error('Photo cropper is not ready.');
            regCropperInstance.setImage(dataUrl);
            if (regCropperEl) regCropperEl.hidden = false;
            if (regError) regError.hidden = true;
        } catch (err) {
            regFail(err.message || 'Could not load that image.');
        } finally {
            regPfpFile.value = '';
        }
    });

    document.getElementById('regCropDone')?.addEventListener('click', () => {
        const latest = regCropperInstance ? regCropperInstance.exportCropped() : '';
        if (latest) {
            regAvatarDataUrl = latest;
            if (regPfpImg) {
                regPfpImg.src = latest;
                regPfpImg.hidden = false;
            }
            if (regPfpFallback) regPfpFallback.hidden = true;
            if (regPfpRemove) regPfpRemove.hidden = false;
        }
        if (regCropperEl) regCropperEl.hidden = true;
        showToast('Photo cropped ✓');
    });

    regPfpRemove?.addEventListener('click', () => {
        regAvatarDataUrl = '';
        if (regCropperInstance) regCropperInstance.reset();
        if (regCropperEl) regCropperEl.hidden = true;
        if (regPfpImg) {
            regPfpImg.hidden = true;
            regPfpImg.removeAttribute('src');
        }
        if (regPfpFallback) regPfpFallback.hidden = false;
        regPfpRemove.hidden = true;
        updateRegReview();
    });

    // Edit-profile cropper wiring.
    const editCropperStage = document.getElementById('editCropStage');
    const editCropImg = document.getElementById('editCropImg');
    const editCropperEl = document.getElementById('editCropper');
    if (editCropperStage && editCropImg) {
        editCropperInstance = createCropper({
            stage: editCropperStage,
            img: editCropImg,
            zoomInput: document.getElementById('editCropZoom'),
            onCrop: dataUrl => {
                editAvatarDataUrl = dataUrl || '';
                const imgEl = document.getElementById('editAvatarPreviewImg');
                if (imgEl) {
                    if (dataUrl) {
                        imgEl.src = dataUrl;
                        imgEl.hidden = false;
                    } else {
                        imgEl.hidden = true;
                    }
                }
                if (editAvatarPreview) editAvatarPreview.hidden = Boolean(dataUrl);
            }
        });
    }

    editPfpFile?.addEventListener('change', async () => {
        const file = editPfpFile.files && editPfpFile.files[0];
        if (!file) return;
        try {
            const dataUrl = await readImageFile(file);
            if (!editCropperInstance) throw new Error('Photo cropper is not ready.');
            editCropperInstance.setImage(dataUrl);
            if (editCropperEl) editCropperEl.hidden = false;
            if (profileSettingsError) profileSettingsError.hidden = true;
        } catch (err) {
            if (profileSettingsError) {
                profileSettingsError.textContent = err.message || 'Could not load that image.';
                profileSettingsError.hidden = false;
            }
        } finally {
            editPfpFile.value = '';
        }
    });

    document.getElementById('editCropDone')?.addEventListener('click', () => {
        const latest = editCropperInstance ? editCropperInstance.exportCropped() : '';
        if (latest) {
            editAvatarDataUrl = latest;
            const imgEl = document.getElementById('editAvatarPreviewImg');
            if (imgEl) {
                imgEl.src = latest;
                imgEl.hidden = false;
            }
            if (editAvatarPreview) editAvatarPreview.hidden = true;
        }
        if (editCropperEl) editCropperEl.hidden = true;
        showToast('Photo cropped ✓');
    });

    editPfpRemove?.addEventListener('click', () => {
        const imgEl = document.getElementById('editAvatarPreviewImg');
        const hadPhoto = Boolean((imgEl && !imgEl.hidden) || editAvatarDataUrl);
        editAvatarDataUrl = '';
        if (editCropperInstance) editCropperInstance.reset();
        if (editCropperEl) editCropperEl.hidden = true;
        if (imgEl) {
            imgEl.hidden = true;
            imgEl.removeAttribute('src');
        }
        if (editAvatarPreview) editAvatarPreview.hidden = false;
        showToast(hadPhoto ? 'Photo removed — press Save to confirm' : 'No photo to remove');
    });

    // Wizard navigation + live helpers.
    regBack?.addEventListener('click', () => {
        if (regStep > 1) showRegStep(regStep - 1);
    });

    regNext?.addEventListener('click', async () => {
        if (regSubmitting) return;
        if (regStep < 3) {
            if (regStep === 1 && regNext) {
                regNext.disabled = true;
                try {
                    await checkRegAvailability();
                } catch (err) {}
                regNext.disabled = false;
            }
            if (!validateRegStep(regStep)) return;
            if (regError) regError.hidden = true;
            showRegStep(regStep + 1);
            return;
        }
        submitRegistration(false);
    });

    regSkipPhoto?.addEventListener('click', () => {
        if (regSubmitting) return;
        submitRegistration(true);
    });

    registerWizard?.addEventListener('submit', event => {
        event.preventDefault();
        regNext?.click();
    });

    regUsername?.addEventListener('input', () => {
        window.clearTimeout(availabilityTimer);
        availabilityTimer = window.setTimeout(checkRegAvailability, 400);
        updateRegReview();
    });
    regDisplayName?.addEventListener('input', updateRegReview);
    regPassword?.addEventListener('input', updatePasswordStrength);
    regBio?.addEventListener('input', () => {
        if (regBioCount && regBio) regBioCount.textContent = `${regBio.value.length}/160`;
    });

})();
