/*
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        scrollToLine: function(lineIndex) {
            if(lineIndex === null || lineIndex === undefined) {
                return null;
            }
            var selector = '[data-line="' + lineIndex + '"]';
            var el = document.querySelector(selector);
            if (el) {
                el.scrollIntoView({behavior: 'smooth', block: 'center'});
                var prevBg = el.style.backgroundColor;
                el.style.backgroundColor = '#333';
                setTimeout(function(){ el.style.backgroundColor = prevBg; }, 1400);
            }
            return null;
        }
    }
});
*/

window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        scrollToLine: function(data) {
            if (!data) return null;

            const line = data.line;
            const page = data.page;

            if (!line || !page) return null;

            let attempts = 0;
            const maxAttempts = 20;  // ~2s total
            const interval = setInterval(() => {
                const el = document.querySelector(
                    `[data-line="${line}"][data-page="${page}"]`
                );

                if (el) {
                    // Scroll smoothly into view
                    el.scrollIntoView({behavior: "smooth", block: "center"});

                    // Add highlight effect
                    el.classList.add("scroll-highlight");

                    // Remove after 2s
                    setTimeout(() => {
                        el.classList.remove("scroll-highlight");
                    }, 2000);

                    clearInterval(interval);
                } else if (++attempts >= maxAttempts) {
                    clearInterval(interval);
                }
            }, 100);

            return null;
        }
    }
});
