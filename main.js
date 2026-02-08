document.addEventListener('DOMContentLoaded', function () {
    const sidebar = document.getElementById('sidebar');
    const content = document.getElementById('content');
    const sidebarCollapse = document.getElementById('sidebarCollapse');
    const overlay = document.querySelector('.overlay');

    sidebarCollapse.addEventListener('click', function () {
        sidebar.classList.toggle('active');
        content.classList.toggle('active'); // Wait, check CSS logic
        // In CSS: #sidebar starts inactive on mobile (margin-left -250px)
        // #sidebar.active means margin-left 0.
        // #content has margin-left 0 on mobile.
        
        // Let's refine the logic based on CSS.
        // Screen > 768px:
        // #sidebar: 0 margin. #sidebar.active: -250px.
        // #content: 250px margin. #sidebar.active + #content: margin-left 0.
        
        // Screen < 768px:
        // #sidebar: -250px margin. #sidebar.active: 0.
        // #content: 0 margin.
        
        // So toggling 'active' class works for both if CSS handles it correctly.
    });
});
