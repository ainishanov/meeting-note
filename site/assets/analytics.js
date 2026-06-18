window.dataLayer = window.dataLayer || [];

(function(m,e,t,r,i,k,a){
  m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
  m[i].l=1*new Date();
  for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
  k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
})(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=109960032', 'ym');

ym(109960032, 'init', {ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true});

(function() {
  var metrikaId = 109960032;

  function reachGoal(goal, target) {
    if (!goal || typeof window.ym !== "function") {
      return;
    }
    window.ym(metrikaId, "reachGoal", goal, {
      href: target && target.href ? target.href : "",
      text: target && target.textContent ? target.textContent.trim() : ""
    });
  }

  function bindGoals() {
    document.querySelectorAll("[data-goal]").forEach(function(link) {
      link.addEventListener("click", function() {
        reachGoal(link.getAttribute("data-goal"), link);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindGoals);
  } else {
    bindGoals();
  }
})();
