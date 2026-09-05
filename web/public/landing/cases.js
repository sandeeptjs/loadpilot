/*! LoadPilot - scenario examples (#projects) motion layer.
 *
 *  Loaded with `defer` from <head>, so it runs before the vendored hobro bundle.
 *  It drops the `.js-subcase` hook, which makes the bundle's casesAnimation()
 *  skip the grid, then re-runs the same reveal correctly:
 *
 *   - the clip-path corner wipe now also opens below 1366px. The original only
 *     tweened `opacity` there and never cleared the closed `--clip-*` values that
 *     are baked into the markup, so every card rendered blank on laptops/tablets.
 *   - card videos start from an IntersectionObserver instead of a tween callback
 *     that a competing tween could cancel, and they keep their playhead instead
 *     of being rewound to frame 0 on every scroll-out.
 *   - `visibility: hidden` is no longer used to park a card, so an interrupted
 *     tween can't leave one permanently invisible. A fully closed inset clip
 *     already paints nothing.
 *   - the 1366px breakpoint is re-evaluated on resize through gsap.matchMedia()
 *     instead of being captured once at load.
 *   - prefers-reduced-motion gets a static, fully open grid with paused video.
 *
 *  Popups, the custom cursor and lazy loading keep their original hooks and
 *  behaviour; nothing in the vendored bundle or markup is modified.
 */
(function () {
  'use strict';

  var SUBS = '.cases__list .cases__subitem';
  var subs = Array.prototype.slice.call(document.querySelectorAll(SUBS));
  if (!subs.length) return;

  // Must happen before the vendored bundle executes.
  subs.forEach(function (sub) {
    sub.classList.remove('js-subcase');
    sub.classList.add('lp-subcase');
  });

  var CORNER = {
    'top right':    { '--clip-top': '0%',   '--clip-right': '0%',   '--clip-bottom': '100%', '--clip-left': '100%' },
    'top left':     { '--clip-top': '0%',   '--clip-right': '100%', '--clip-bottom': '100%', '--clip-left': '0%'   },
    'bottom left':  { '--clip-top': '100%', '--clip-right': '100%', '--clip-bottom': '0%',   '--clip-left': '0%'   },
    'bottom right': { '--clip-top': '100%', '--clip-right': '0%',   '--clip-bottom': '0%',   '--clip-left': '100%' }
  };
  var OPEN = { '--clip-top': '0%', '--clip-right': '0%', '--clip-bottom': '0%', '--clip-left': '0%' };
  var IN  = ['top right', 'top left', 'bottom left', 'bottom right'];
  var OUT = ['bottom left', 'bottom right', 'top right', 'top left'];
  var DUR = 1;

  function merge() {
    var out = {}, i, k;
    for (i = 0; i < arguments.length; i++) {
      for (k in arguments[i]) if (Object.prototype.hasOwnProperty.call(arguments[i], k)) out[k] = arguments[i][k];
    }
    return out;
  }

  /* ---------------------------------------------------------------- playback */

  var videos = subs.map(function (s) { return s.querySelector('.js-case-video'); })
                   .filter(Boolean);
  var wanted = [];   // videos currently in view
  var allowPlay = true;

  function inWanted(v) { return wanted.indexOf(v) > -1; }

  function ensureSrc(v) {
    var dirty = false;
    Array.prototype.forEach.call(v.querySelectorAll('source'), function (s) {
      var want = s.dataset.src;
      if (want && s.getAttribute('src') !== want) { s.setAttribute('src', want); dirty = true; }
    });
    if (dirty) { try { v.load(); } catch (e) {} }
  }

  function play(v) {
    if (!allowPlay || document.hidden || !inWanted(v)) return;
    if (document.body.classList.contains('is-popup-open')) return;
    ensureSrc(v);
    v.dataset.play = 'true';
    var p = v.play();
    if (p && p.catch) {
      p.catch(function () {
        // A pause() landing mid-play rejects the promise; retry once there is data.
        v.addEventListener('loadeddata', function () { play(v); }, { once: true });
      });
    }
  }

  function stop(v) {
    v.dataset.play = 'false';
    try { v.pause(); } catch (e) {}   // deliberately no currentTime reset
  }

  function syncAll() { videos.forEach(function (v) { inWanted(v) ? play(v) : stop(v); }); }

  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var v = e.target.querySelector('.js-case-video');
        if (!v) return;
        var at = wanted.indexOf(v);
        if (e.isIntersecting) { if (at < 0) wanted.push(v); play(v); }
        else { if (at > -1) wanted.splice(at, 1); stop(v); }
      });
    }, { threshold: 0.2 });
    subs.forEach(function (s) { io.observe(s); });
  } else {
    videos.forEach(function (v) { wanted.push(v); });
  }

  document.addEventListener('visibilitychange', syncAll);

  // The bundle pauses card videos when a popup opens; keep that decision.
  var popupWas = false;
  if ('MutationObserver' in window) {
    new MutationObserver(function () {
      var open = document.body.classList.contains('is-popup-open');
      if (open === popupWas) return;
      popupWas = open;
      syncAll();
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  /* ----------------------------------------------------------------- reveal */

  function build() {
    var gsap = window.gsap, ST = window.ScrollTrigger;
    document.documentElement.classList.add('lp-cases-armed');
    var mm = gsap.matchMedia();

    mm.add({ wide: '(min-width: 1366px)', narrow: '(max-width: 1365px)', reduce: '(prefers-reduced-motion: reduce)' }, function (ctx) {
      var wide = ctx.conditions.wide;
      var reduce = ctx.conditions.reduce;
      var cleanups = [];
      allowPlay = !reduce;

      subs.forEach(function (sub, i) {
        var asset = sub.querySelector('.js-case-asset');
        var name  = sub.querySelector('.js-case-name');
        var video = sub.querySelector('.js-case-video');
        if (!asset) return;

        asset.classList.add('cases__asset--clip');

        var inFrom = CORNER[IN[i % 4]];
        var outTo  = CORNER[OUT[i % 4]];
        var clipT = null, nameT = null, radiusT = null;
        var open = false;

        function clipTo(vars, dur) {
          if (clipT) clipT.kill();
          clipT = gsap.to(asset, merge(vars, {
            duration: dur,
            overwrite: false,
            onStart: function () { asset.style.willChange = wide ? 'clip-path' : 'opacity'; },
            onComplete: function () { asset.style.willChange = ''; }
          }));
        }
        function nameTo(vars, dur) {
          if (!name) return;
          if (nameT) nameT.kill();
          nameT = gsap.to(name, merge(vars, { duration: dur }));
        }

        function show() {
          if (open) return;
          open = true;
          if (wide) { clipTo(OPEN, DUR); nameTo({ yPercent: 0, opacity: 1 }, DUR); }
          else      { clipTo(merge(OPEN, { opacity: 1 }), DUR); nameTo({ opacity: 1 }, DUR); }
        }
        function hide(corner) {
          if (!open) return;
          open = false;
          if (wide) { clipTo(corner, DUR); nameTo({ yPercent: 300, opacity: 0 }, DUR); }
          else      { clipTo({ opacity: 0 }, DUR); nameTo({ opacity: 0 }, DUR); }
        }

        // Initial state. Narrow viewports keep the clip open and fade instead --
        // the markup ships closed --clip-* values, which is what used to leave the
        // whole grid blank under 1366px.
        if (reduce) {
          gsap.set(asset, merge(OPEN, { opacity: 1 }));
          if (name) gsap.set(name, { yPercent: 0, opacity: 1, clearProps: 'transform' });
          open = true;
          if (video) stop(video);
          return;
        }
        if (wide) {
          gsap.set(asset, merge(inFrom, { opacity: 1 }));
          if (name) gsap.set(name, { yPercent: 300, opacity: 0 });
        } else {
          gsap.set(asset, merge(OPEN, { opacity: 0 }));
          if (name) gsap.set(name, { yPercent: 0, opacity: 0 });
        }

        var st = ST.create({
          id: 'lp-case-' + i,
          trigger: sub,
          start: 'clamp(top+=20% bottom)',
          end: 'clamp(bottom+=100% top)',
          invalidateOnRefresh: true,
          onEnter: show,
          onEnterBack: show,
          onLeave: function () { hide(outTo); },
          onLeaveBack: function () { hide(inFrom); }
        });

        function radius(px) {
          if (!wide) return;
          if (radiusT) radiusT.kill();
          radiusT = gsap.to(asset, { '--clip-radius': px + 'px', duration: DUR, ease: 'power1.inOut' });
        }
        var enter = function () { radius(30); };
        var leave = function () { radius(0); };
        sub.addEventListener('mouseenter', enter);
        sub.addEventListener('mouseleave', leave);

        cleanups.push(function () {
          st.kill();
          sub.removeEventListener('mouseenter', enter);
          sub.removeEventListener('mouseleave', leave);
          if (clipT) clipT.kill();
          if (nameT) nameT.kill();
          if (radiusT) radiusT.kill();
        });
      });

      return function () { cleanups.forEach(function (fn) { fn(); }); };
    });
  }

  function boot() {
    var tries = 0;
    (function wait() {
      if (window.gsap && window.ScrollTrigger && window.gsap.matchMedia) { build(); return; }
      if (++tries > 200) return;              // ~4s, then give up quietly
      requestAnimationFrame(wait);
    })();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
