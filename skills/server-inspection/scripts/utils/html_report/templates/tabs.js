(function() {
    var btns = document.querySelectorAll(".tab-btn");
    var panels = document.querySelectorAll(".tab-panel");
    btns.forEach(function(btn) {
        btn.addEventListener("click", function() {
            var id = btn.getAttribute("data-tab");
            btns.forEach(function(b) { b.classList.remove("active"); });
            panels.forEach(function(p) { p.classList.remove("active"); });
            btn.classList.add("active");
            var panel = document.getElementById(id);
            if (panel) panel.classList.add("active");
        });
    });
})();