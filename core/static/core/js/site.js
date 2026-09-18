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
    const formatter = new Intl.NumberFormat('ar-EG', { useGrouping: false });
    let toastTimer;
    let currentTab = 'all';
    let searchTerm = '';
    let isPublishing = false;

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
        toast.classList.add('is-visible');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2800);
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
                <button class="more-button" type="button" data-toast="خيارات المنشور" aria-label="المزيد"><svg viewBox="0 0 24 24" fill="none"><circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/></svg></button>
            </div>
            <div class="post-body">
                <p>${escapeHTML(post.body || '')}</p>
                ${tags.length ? `<div class="post-tags">${tags.map(tag => `<span>#${escapeHTML(tag)}</span>`).join('')}</div>` : ''}
            </div>
            <div class="post-actions">
                <button class="post-action action-reply" type="button" data-action="reply" aria-label="الرد على المنشور">${icons.reply}<span data-count="replies">${number(post.replies)}</span></button>
                <button class="post-action action-repost" type="button" data-action="repost" aria-label="إعادة نشر">${icons.repost}<span data-count="reposts">${number(post.reposts)}</span></button>
                <button class="post-action action-like" type="button" data-action="like" aria-label="الإعجاب بالمنشور">${icons.like}<span data-count="likes">${number(post.likes)}</span></button>
                <button class="post-action action-bookmark" type="button" data-action="bookmark" aria-label="حفظ المنشور">${icons.bookmark}</button>
                <button class="post-action action-share" type="button" data-action="share" aria-label="مشاركة المنشور">${icons.share}</button>
            </div>`;
        return article;
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
        isPublishing = true;
        updateComposerState();
        publishButton.textContent = 'جارٍ النشر…';
        try {
            const response = await fetch('/api/posts/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ body })
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'تعذّر النشر');
            const card = renderPost(payload.post);
            feedList.prepend(card);
            postInput.value = '';
            currentTab = 'all';
            document.querySelectorAll('[data-feed-tab]').forEach(tab => {
                const active = tab.dataset.feedTab === 'all';
                tab.classList.toggle('is-active', active);
                tab.setAttribute('aria-selected', active ? 'true' : 'false');
            });
            updateVisibility();
            showToast('تركْت أثرًا جديدًا في المساحة');
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

    function filterFromSearch() {
        if (!searchInput) return;
        searchTerm = searchInput.value.trim();
        if (searchHint) {
            searchHint.textContent = searchTerm
                ? `نتائج البحث عن «${searchTerm}» تتحدث مع كل حرف.`
                : 'اكتب كلمة للبحث في الأصوات والمنشورات والمواضيع.';
        }
        updateVisibility();
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

    // One delegated listener keeps dynamically published posts interactive too.
    document.addEventListener('click', event => {
        const openComposer = event.target.closest('[data-open-composer]');
        if (openComposer) {
            event.preventDefault();
            scrollToComposer();
            return;
        }

        const toastTarget = event.target.closest('[data-toast]');
        if (toastTarget) {
            event.preventDefault();
            showToast(toastTarget.dataset.toast);
            return;
        }

        const follow = event.target.closest('[data-follow-button]');
        if (follow) {
            const following = follow.classList.toggle('is-following');
            follow.textContent = following ? 'تتابع' : 'تابع';
            follow.setAttribute('aria-pressed', following ? 'true' : 'false');
            showToast(following ? 'أضفناه إلى دوائرك' : 'أزلناه من دوائرك');
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
        if (actionType === 'like' || actionType === 'repost') {
            const active = action.classList.toggle('is-active');
            const count = action.querySelector(`[data-count="${actionType === 'like' ? 'likes' : 'reposts'}"]`);
            if (count) count.textContent = number(numericValue(count.textContent) + (active ? 1 : -1));
            if (active) showToast(actionType === 'like' ? 'وصل إعجابك' : 'أعدت نشر هذا الأثر');
            return;
        }
        if (actionType === 'bookmark') {
            const active = action.classList.toggle('is-active');
            showToast(active ? 'حُفظ في مجموعتك' : 'أزيل من مجموعتك');
            return;
        }
        if (actionType === 'reply') {
            scrollToComposer();
            showToast('اكتب ردّك في مساحة الكتابة');
            return;
        }
        if (actionType === 'share') {
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
        if (event.key === '/' && document.activeElement?.tagName !== 'TEXTAREA' && document.activeElement?.tagName !== 'INPUT') {
            event.preventDefault();
            openSearch();
        }
    });

    document.getElementById('newsletterForm')?.addEventListener('submit', event => {
        event.preventDefault();
        const input = event.currentTarget.querySelector('input');
        if (input?.value) {
            event.currentTarget.reset();
            showToast('أهلًا بك — ستصلك أول رسالة قريبًا');
        }
    });
})();
