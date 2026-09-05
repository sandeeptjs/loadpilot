// Closing orbit adapted from the user-supplied Kononenko reference.
document.addEventListener('DOMContentLoaded', () => {
  const section = document.querySelector('.lp-orbit-section')
  const stage = document.querySelector('.lp-orbit-stage')
  const discs = Array.from(document.querySelectorAll('.lp-orbit-disc'))
  if (!section || !stage) return
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  let width = stage.clientWidth
  let height = stage.clientHeight
  const cumulative = new Float64Array(361)
  function measure() {
    width = stage.clientWidth
    height = Math.min(stage.clientHeight, window.innerHeight)
    const rx = width * .36
    const ry = height * .42
    let length = 0
    for (let i = 1; i <= 360; i++) {
      const angle = (i - .5) * Math.PI * 2 / 360
      length += Math.hypot(rx * Math.cos(angle), ry * Math.sin(angle))
      cumulative[i] = length
    }
    for (let i = 1; i <= 360; i++) cumulative[i] /= length || 1
  }
  function angleAt(fraction) {
    const position = ((fraction % 1) + 1) % 1
    let low = 0, high = 360
    while (low < high) {
      const middle = (low + high) >> 1
      if (cumulative[middle] < position) low = middle + 1
      else high = middle
    }
    if (!low) return 0
    const blend = (position - cumulative[low - 1]) / (cumulative[low] - cumulative[low - 1])
    return (low - 1 + blend) / 360 * Math.PI * 2
  }
  let phase = 0
  let last = 0
  let lastScroll = window.scrollY
  let acceleration = 0
  let visible = false
  let frame = 0
  function draw() {
    const tilt = -.3
    discs.forEach((disc, index) => {
      const angle = angleAt(index / discs.length + phase)
      const depth = (Math.cos(angle) + 1) / 2
      const x = Math.sin(angle) * width * .36
      const y = Math.cos(angle) * height * .42
      const scale = .7 + depth * .3
      disc.style.transform = `translate(-50%, -50%) translate(${x * Math.cos(tilt) - y * Math.sin(tilt)}px, ${x * Math.sin(tilt) + y * Math.cos(tilt)}px) scale(${scale})`
      disc.style.opacity = String(.1 + Math.pow(depth, 1.4) * .9)
      disc.style.zIndex = Math.cos(angle) > 0 ? '3' : '1'
    })
  }
  function animate(time) {
    frame = 0
    if (!visible || document.hidden || reducedMotion.matches) return
    const dt = last ? Math.min((time - last) / 1000, .05) : 0
    last = time
    const delta = window.scrollY - lastScroll
    lastScroll = window.scrollY
    const velocity = dt ? delta / dt : 0
    const target = Math.sign(velocity) * Math.min(.6, Math.pow(Math.max(0, Math.abs(velocity) - 100) / 112000, .6))
    acceleration += (target - acceleration) * (1 - Math.pow(.9, dt * 60))
    phase += (dt + acceleration * dt * 60) / (Math.PI * 6)
    draw()
    frame = requestAnimationFrame(animate)
  }
  function resume() {
    cancelAnimationFrame(frame)
    last = 0
    lastScroll = window.scrollY
    draw()
    if (visible && !document.hidden && !reducedMotion.matches) frame = requestAnimationFrame(animate)
  }
  measure()
  draw()
  new ResizeObserver(() => { measure(); draw() }).observe(stage)
  new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting
    resume()
  }, { rootMargin: '100px' }).observe(section)
  document.addEventListener('visibilitychange', resume)
  reducedMotion.addEventListener('change', resume)
  if (window.gsap && window.ScrollTrigger) {
    window.gsap.matchMedia().add('(prefers-reduced-motion: no-preference)', () => {
      window.gsap.from(section.querySelectorAll('.lp-orbit-line > span'), {
        yPercent: 101,
        duration: 1.15,
        stagger: .07,
        ease: 'power3.out',
        scrollTrigger: { trigger: section, start: 'top 75%', toggleActions: 'play none none reverse' },
      })
    })
  }
})
