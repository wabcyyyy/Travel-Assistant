import { useLocation } from '../router'
import { HomeStudio } from './HomeStudio'
import { HomeInspiration } from './HomeInspiration'
import { HomeJournal } from './HomeJournal'
import { Icon } from '../shared/Icon'
import { navigate } from '../router'
import hangzhou from '../../assets/img/cover-hangzhou.webp'

export function HomePage() {
  const { query } = useLocation()
  return <div className="home-page">
    <section className="home-intro" aria-labelledby="home-title">
      <div className="home-story">
        <h1 id="home-title">下一站，<br />想怎么过？</h1>
        <p className="home-description">想去的地方，喜欢的节奏。<br />说给司南听，一起安排成行。</p>
        <figure className="home-postcard">
          <img src={hangzhou} alt="落日下的杭州西湖，湖面与荷叶映着金色的光" width="1280" height="728" fetchPriority="high" />
          <figcaption><span><Icon name="pin" size={15} />杭州 · 把周末留给湖光</span><button type="button" aria-label="阅读杭州旅行攻略" onClick={() => navigate('/guides/hangzhou-by-the-lake')}><Icon name="arrowUpRight" size={20} /></button></figcaption>
        </figure>
      </div>
      <HomeStudio key={query.toString()} query={query} />
    </section>
    <HomeInspiration />
    <HomeJournal />
  </div>
}
