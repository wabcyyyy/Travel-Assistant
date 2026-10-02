import { inspirationTemplates } from '../data'
import { navigate } from '../router'
import { Icon } from '../shared/Icon'
import { SmartImg } from '../shared/SmartImg'

const suggestions = inspirationTemplates.filter((item) => ['chengdu-slow', 'shanghai-walk', 'xian-food', 'chongqing-night'].includes(item.id))

export function HomeInspiration() {
  return <section className="home-inspiration" aria-labelledby="inspiration-title">
    <div className="home-inspiration-heading"><div><h2 id="inspiration-title">还没想好？从这里出发。</h2><p>把一段向往，变成下一次出发的理由。</p></div><button className="text-action" type="button" onClick={() => navigate('/inspiration')}>更多旅行灵感<Icon name="arrowUpRight" size={16} /></button></div>
    <div className="home-destination-pair">{suggestions.map((item) => <button key={item.id} className="home-destination" type="button" onClick={() => navigate(`/?template=${item.id}`)}>
      <div className="home-destination-photo"><SmartImg src={item.image} alt={`${item.city}城市风景`} /></div>
      <div className="home-destination-caption"><div><span>{item.city} / {item.days} 天</span><h3>{item.title}</h3></div><span className="home-destination-arrow"><Icon name="arrowUpRight" size={19} /></span></div>
      <p className="home-destination-description">{item.description}</p>
    </button>)}</div>
  </section>
}
