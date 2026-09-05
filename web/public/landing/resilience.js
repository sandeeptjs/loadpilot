// Optional media must not keep the exported page behind its loading curtain.
if ('scrollRestoration' in history) history.scrollRestoration = 'manual'
document.addEventListener('DOMContentLoaded', () => {
  if (!location.hash) window.scrollTo(0, 0)
  document.querySelectorAll('dotlottie-player').forEach(player => {
    player.addEventListener('ready', () => { player.dataset.ready = 'true' })
    player.addEventListener('error', () => { player.style.visibility = 'hidden' })
  })
  setTimeout(() => {
    if (window.isLoaderComplete) return
    document.querySelector('.js-loader')?.style.setProperty('display', 'none', 'important')
    document.body.classList.remove('loading')
    document.querySelector('.js-header')?.style.setProperty('opacity', '1')
    window.isLoaderExited = true
    window.isLoaderComplete = true
    window.dispatchEvent(new Event('loaderExited'))
    window.dispatchEvent(new Event('loaderComplete'))
  }, 9000)
})
