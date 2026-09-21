import Link from "next/link";
import { Icon, type IconName } from "../icons";

export const metadata = {
  title: "Cómo jugar Commander — Reglas para principiantes",
  description:
    "Guía simple para aprender a jugar Magic: The Gathering en formato Commander: el objetivo, las zonas, el turno, el combate, el comandante y las palabras clave.",
};

function Section({ id, icon, title, children }: {
  id: string; icon: IconName; title: string; children: React.ReactNode;
}) {
  return (
    <div className="card" id={id} style={{ scrollMarginTop: 80 }}>
      <h2><Icon name={icon} size={20} /> {title}</h2>
      {children}
    </div>
  );
}

const KEYWORDS: { k: string; d: string }[] = [
  { k: "Flying (Volar)", d: "Solo puede ser bloqueada por criaturas con volar o alcance." },
  { k: "Trample (Arrollar)", d: "El daño que sobra tras matar al bloqueador pasa al jugador." },
  { k: "Deathtouch (Toque mortal)", d: "Cualquier cantidad de daño que haga destruye a la criatura." },
  { k: "Lifelink (Vínculo vital)", d: "Cuando hace daño, ganás esa misma cantidad de vida." },
  { k: "Vigilance (Vigilancia)", d: "No se gira al atacar, así que sigue pudiendo bloquear." },
  { k: "Haste (Prisa)", d: "Puede atacar y usar habilidades de girar el turno que entra." },
  { k: "Menace (Amenaza)", d: "Necesita dos o más criaturas para ser bloqueada." },
  { k: "Hexproof (Antimaleficio)", d: "Tus oponentes no pueden hacerla objetivo de hechizos ni habilidades." },
  { k: "First strike (Dañar primero)", d: "Hace su daño de combate antes que las criaturas normales." },
  { k: "Double strike (Dañar doble)", d: "Hace daño en el paso de dañar primero y en el normal." },
  { k: "Defender (Defensor)", d: "No puede atacar (suele ser un muro para defenderte)." },
  { k: "Reach (Alcance)", d: "Puede bloquear criaturas con volar." },
];

export default function ReglasPage() {
  return (
    <div className="wrap">
      <header>
        <h1><Icon name="book" size={26} /> Cómo jugar Commander</h1>
        <p>
          ¿Primera vez con Magic? Acá van las bases del formato Commander, en criollo y
          sin vueltas. No hace falta memorizar nada: leelo una vez y probá una partida.
        </p>
      </header>

      <div className="card">
        <h2><Icon name="scroll" size={20} /> En esta guía</h2>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          {[
            ["que-es", "Qué es Commander"], ["objetivo", "El objetivo"],
            ["mazo", "Tu mazo"], ["comandante", "El comandante"],
            ["zonas", "Las zonas"], ["turno", "El turno"],
            ["mana", "El maná"], ["tipos", "Tipos de carta"],
            ["combate", "El combate"], ["mulligan", "El mulligan"],
            ["keywords", "Palabras clave"], ["ganar", "Cómo se gana"],
          ].map(([id, label]) => (
            <a key={id} href={`#${id}`} className="chip" style={{ textDecoration: "none" }}>{label}</a>
          ))}
        </div>
      </div>

      <Section id="que-es" icon="crown" title="Qué es Commander">
        <p>
          Commander (o EDH) es la forma más popular de jugar Magic en grupo. Lo normal es
          una mesa de <b>3 o 4 jugadores</b>, cada uno con su propio mazo, y se juega
          <b> todos contra todos</b>.
        </p>
        <ul className="abil">
          <li>Cada jugador arranca con <b>40 puntos de vida</b> (en 1v1 normal son 20).</li>
          <li>El mazo tiene <b>exactamente 100 cartas</b>, una de ellas es tu <b>comandante</b>.</li>
          <li>Las partidas son más largas y con jugadas grandes: es un formato para pasarla bien.</li>
        </ul>
      </Section>

      <Section id="objetivo" icon="trophy" title="El objetivo">
        <p>Ganás cuando sos el <b>último en pie</b>. Un jugador queda eliminado si:</p>
        <ul className="abil">
          <li>su vida llega a <b>0</b> (por daño de criaturas o hechizos),</li>
          <li>recibe <b>21 de daño de un mismo comandante</b> (la regla especial del formato),</li>
          <li>o junta <b>10 contadores de veneno</b>.</li>
        </ul>
        <p className="muted" style={{ fontSize: ".85rem" }}>
          También se pierde si tenés que robar de una biblioteca vacía. Y hay cartas que
          ganan la partida de formas alternativas (esas son la excepción, no la regla).
        </p>
      </Section>

      <Section id="mazo" icon="cards" title="Tu mazo (100 cartas)">
        <ul className="abil">
          <li><b>Singleton:</b> solo <b>una copia</b> de cada carta… salvo las tierras
            básicas (Plains, Island, Swamp, Mountain, Forest), de esas podés poner las que quieras.</li>
          <li><b>Identidad de color:</b> todas tus cartas deben estar dentro de los colores
            de tu comandante. Si tu comandante es rojo-blanco, no podés meter cartas azules.</li>
          <li>Un mazo típico lleva alrededor de <b>37 tierras</b> y el resto criaturas,
            hechizos y artefactos. Con muy pocas tierras te trabás; con demasiadas, no hacés nada.</li>
        </ul>
      </Section>

      <Section id="comandante" icon="crown" title="El comandante">
        <p>
          Es una criatura legendaria que dirige tu mazo. Empieza en la <b>zona de mando</b>
          (no en tu biblioteca) y podés lanzarla desde ahí en cualquier momento en que
          puedas jugar una criatura.
        </p>
        <ul className="abil">
          <li><b>Impuesto de comandante:</b> cada vez que tu comandante vuelve a la zona de
            mando y lo relanzás, cuesta <b>2 de maná más</b> por cada vez anterior.</li>
          <li><b>Daño de comandante:</b> si una sola criatura-comandante te pega <b>21 de
            daño</b> en total durante la partida, quedás eliminado (aunque tu vida no sea 0).</li>
        </ul>
      </Section>

      <Section id="zonas" icon="library" title="Las zonas del juego">
        <ul className="abil">
          <li><b>Mano:</b> las cartas que tenés para jugar.</li>
          <li><b>Biblioteca:</b> tu mazo boca abajo, de donde robás.</li>
          <li><b>Campo de batalla:</b> lo que está en juego (tierras, criaturas, etc.).</li>
          <li><b>Cementerio:</b> tus cartas destruidas, descartadas o usadas.</li>
          <li><b>Exilio:</b> una &quot;afuera&quot; especial: lo que va acá suele no volver.</li>
          <li><b>Zona de mando:</b> donde vive tu comandante.</li>
        </ul>
      </Section>

      <Section id="turno" icon="refresh" title="El turno, paso a paso">
        <p>Cada turno sigue siempre el mismo orden:</p>
        <ol className="abil">
          <li><b>Enderezar:</b> girás de vuelta (&quot;desgirás&quot;) tus cartas giradas.</li>
          <li><b>Mantenimiento:</b> se disparan efectos de &quot;al comienzo de tu turno&quot;.</li>
          <li><b>Robar:</b> robás una carta (el que empieza la partida no roba en su primer turno).</li>
          <li><b>Primera fase principal:</b> jugás tierras, criaturas, hechizos.</li>
          <li><b>Combate:</b> declarás atacantes, el rival declara bloqueadores, se reparte el daño.</li>
          <li><b>Segunda fase principal:</b> otra ventana para jugar cartas.</li>
          <li><b>Final:</b> se limpian daños y termina el turno.</li>
        </ol>
        <p className="muted" style={{ fontSize: ".85rem" }}>
          Normalmente jugás <b>una tierra por turno</b>. Girar una carta (&quot;taparla&quot;)
          es la forma de usarla: las tierras se giran para dar maná, las criaturas se giran para atacar.
        </p>
      </Section>

      <Section id="mana" icon="bolt" title="El maná y los colores">
        <p>
          El maná es la energía para lanzar cartas. Hay cinco colores —
          <b> W</b> blanco, <b>U</b> azul, <b>B</b> negro, <b>R</b> rojo, <b>G</b> verde —
          más el maná incoloro.
        </p>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", margin: "8px 0" }}>
          <span className="chip"><b>W</b> Blanco · orden, vida</span>
          <span className="chip"><b>U</b> Azul · robo, control</span>
          <span className="chip"><b>B</b> Negro · muerte, sacrificio</span>
          <span className="chip"><b>R</b> Rojo · daño, velocidad</span>
          <span className="chip"><b>G</b> Verde · criaturas, maná</span>
        </div>
        <p>
          El coste de una carta como <b>2R</b> significa &quot;2 de maná de cualquier color
          + 1 rojo&quot;. Girás tierras para generar ese maná y pagarlo.
        </p>
      </Section>

      <Section id="tipos" icon="scroll" title="Tipos de carta">
        <ul className="abil">
          <li><b>Tierra:</b> tu fuente de maná. Solo podés jugar una por turno.</li>
          <li><b>Criatura:</b> ataca y bloquea. Tiene fuerza/resistencia (ej. 2/3).</li>
          <li><b>Artefacto:</b> objeto; muchos dan maná o efectos permanentes.</li>
          <li><b>Encantamiento:</b> efecto permanente que se queda en juego.</li>
          <li><b>Planeswalker:</b> un aliado con lealtad; usás <b>una</b> de sus habilidades por turno.</li>
          <li><b>Instantáneo:</b> lo podés jugar en cualquier momento, incluso en el turno del rival.</li>
          <li><b>Conjuro:</b> como el instantáneo, pero solo en tu fase principal, con la pila vacía.</li>
        </ul>
      </Section>

      <Section id="combate" icon="swords" title="El combate">
        <ol className="abil">
          <li>En tu combate, elegís qué criaturas <b>atacan</b> y a quién (podés atacar a distintos rivales).</li>
          <li>El defensor elige con qué criaturas <b>bloquea</b> cada atacante.</li>
          <li>Se reparte el daño: fuerza contra resistencia. Una criatura muere si recibe daño igual o mayor a su resistencia.</li>
          <li>El daño de un atacante <b>sin bloquear</b> va directo a la vida del jugador.</li>
        </ol>
        <p className="muted" style={{ fontSize: ".85rem" }}>
          Palabras como <b>volar</b>, <b>arrollar</b> o <b>dañar primero</b> cambian cómo
          funciona el combate — mirá el glosario más abajo.
        </p>
      </Section>

      <Section id="mulligan" icon="hand" title="El mulligan (cambiar la mano)">
        <p>
          Si tu mano inicial de 7 no te gusta (muchas tierras, o muy pocas), podés
          hacer <b>mulligan</b>: barajás, robás 7 nuevas y decidís de nuevo.
        </p>
        <ul className="abil">
          <li>En Commander, el <b>primer mulligan es gratis</b>.</li>
          <li>A partir del segundo, por cada mulligan ponés <b>1 carta al fondo</b> de tu biblioteca al quedarte.</li>
          <li>Buena regla para arrancar: quedate con manos de <b>2 a 4 tierras</b>.</li>
        </ul>
      </Section>

      <Section id="keywords" icon="sparkles" title="Palabras clave más comunes">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
          {KEYWORDS.map((kw) => (
            <div key={kw.k} className="combo" style={{ margin: 0 }}>
              <div><b>{kw.k}</b></div>
              <div className="muted" style={{ fontSize: ".84rem" }}>{kw.d}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section id="ganar" icon="trophy" title="Cómo se gana (resumen)">
        <ul className="abil">
          <li>Bajá la vida de todos tus rivales a <b>0</b>, o</li>
          <li>pegá <b>21 de daño de comandante</b> a alguien, o</li>
          <li>juntá que un rival tenga <b>10 de veneno</b>, o</li>
          <li>hacé que se quede <b>sin cartas para robar</b>.</li>
        </ul>
        <p>El último jugador que queda en la mesa gana la partida.</p>
      </Section>

      <div className="card" style={{ background: "linear-gradient(180deg, rgba(216,178,58,.10), transparent)", borderColor: "rgba(216,178,58,.5)" }}>
        <h2><Icon name="gamepad" size={20} /> Ahora probá</h2>
        <p>La mejor forma de aprender es jugando. Empezá con lo que quieras:</p>
        <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
          <Link className="go" href="/play" style={{ textDecoration: "none" }}>Jugar contra el sistema</Link>
          <Link className="ghost" href="/watch" style={{ textDecoration: "none" }}>Ver una partida de ejemplo</Link>
          <Link className="ghost" href="/deck" style={{ textDecoration: "none" }}>Armar un deck</Link>
        </div>
        <p className="muted" style={{ fontSize: ".82rem", marginTop: 10 }}>
          En &quot;Jugar&quot; vos manejás tu turno y el sistema juega los rivales, así vas
          agarrando la mano sin apuro.
        </p>
      </div>

      <footer>
        Esta guía cubre lo básico para arrancar; las reglas oficiales completas de Magic
        tienen más detalle. Proyecto fan, no afiliado a Wizards of the Coast.
      </footer>
    </div>
  );
}
