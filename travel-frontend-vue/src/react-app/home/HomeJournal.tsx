import { guides } from '../data'
import { navigate } from '../router'
import { Icon } from '../shared/Icon'

export function HomeJournal() {
  return <section className="home-journal" aria-labelledby="journal-title">
    <div className="home-journal-intro">
      <h2 id="journal-title">先读一点城市，<br />再去遇见它。</h2>
      <p>从街巷到茶山，把值得停留的日常，放进你的下一次旅行。</p>
      <button className="text-action" type="button" onClick={() => navigate('/guides')}>翻开旅行攻略<Icon name="arrowUpRight" size={17} /></button>
    </div>
    <div className="home-journal-list">{guides.slice(0, 2).map((guide) => <button key={guide.slug} className="home-journal-entry" type="button" onClick={() => navigate(`/guides/${guide.slug}`)}>
      <img src={guide.image} alt={`${guide.city}城市风景`} width="160" height="120" loading="lazy" />
      <span className="home-journal-copy"><small>{guide.tag} · {guide.readTime}</small><strong>{guide.title}</strong><span>{guide.excerpt}</span></span>
      <Icon name="arrowUpRight" size={20} />
    </button>)}</div>
  </section>
}
