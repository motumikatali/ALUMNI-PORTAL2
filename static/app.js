document.addEventListener('DOMContentLoaded', function () {
    const themeToggle = document.getElementById('themeToggle');
    const storedTheme = localStorage.getItem('portal-theme') || 'dark';

    if (themeToggle) {
        const applyTheme = (theme) => {
            document.body.setAttribute('data-theme', theme);
            const icon = themeToggle.querySelector('i');
            if (icon) {
                icon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
            }
            if (themeToggle.querySelector('.theme-label')) {
                themeToggle.querySelector('.theme-label').textContent = theme === 'dark' ? 'Light' : 'Dark';
            }
        };

        themeToggle.addEventListener('click', function () {
            const nextTheme = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            localStorage.setItem('portal-theme', nextTheme);
            applyTheme(nextTheme);
        });

        applyTheme(storedTheme);
    }
});
