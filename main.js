document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    const sidebarCollapse = document.getElementById('sidebarCollapse');
    const overlay = document.querySelector('.overlay');

    sidebarCollapse.addEventListener('click', function () {
        sidebar.classList.toggle('active');
        content.classList.toggle('active');
    });
});
