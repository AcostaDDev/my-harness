import { useI18n } from "../Language";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Empty, Loading, PageHeader, Stale, usePoll } from "../ui";

export function Home() {
  const { t, rich } = useI18n();
  const projects = usePoll<S["ManagedProjectRead"][]>("/projects", 5000);
  const registry = usePoll<S["RegistryRead"]>("/registry", 15000);
  const list = projects.data;
  const available = registry.data?.available;
  const unavailable = registry.data?.projects.filter(p => p.status === "ACTIVE" && !p.available) ?? [];
  return <>
    <PageHeader title={t("home.title")} aside={available ? <Link className="button-link" to={{ name: "project-new" }}>{t("home.register")}</Link> : undefined}>
      <p>{t("home.lede")}</p>
    </PageHeader>
    <Stale error={list ? projects.error : undefined} />
    {unavailable.length > 0 && <div className="state state-attention" role="status">
      <p className="state-title">{t("home.unavailable")}</p>
      <ul>{unavailable.map(p => <li key={p.id}><code>{p.id}</code>: {p.diagnostic}</li>)}</ul>
    </div>}
    {!list ? projects.error ? <p role="alert" className="state state-error">{t("home.read_failed", { error: projects.error })}</p> : <Loading>{t("home.loading")}</Loading>
      : !list.length ? <Empty title={t("home.empty.title")}>
        {available ? <p>{t("home.empty.register")} <Link to={{ name: "project-new" }}>{t("home.register")}</Link></p>
          : <p>{rich("home.empty.operator", { command: <code>my-harness serve --config</code>, formats: <code>local-config-3/4/5/6/7</code>, section: <code>[registration]</code> })}</p>}
      </Empty>
        : <div className="table-scroll" role="region" aria-label={t("home.table")} tabIndex={0}>
          <table className="table">
            <thead><tr><th scope="col">{t("home.column.project")}</th><th scope="col">{t("home.column.source")}</th><th scope="col">{t("home.column.profile")}</th><th scope="col">{t("home.column.documents")}</th><th scope="col">{t("home.column.reviewer")}</th><th scope="col">{t("home.column.executor")}</th><th scope="col">{t("home.column.checkout")}</th></tr></thead>
            <tbody>{list.map(p => <tr key={p.id}>
              <td><Link className="mono strong" to={{ name: "project", project: p.id }}>{p.id}</Link></td>
              <td className="nowrap">{p.source === "registry" ? t("home.source.registry", { version: p.registry_version ?? "" }) : "TOML"}</td>
              <td className="nowrap">{p.profile}</td>
              <td>{p.documents === "v2" ? t("home.documents.v2") : t("home.documents.legacy")}</td>
              <td>{p.agents.reviewer.provider ?? t("common.undeclared")} <span className="muted">{p.agents.reviewer.model}</span></td>
              <td>{p.agents.executor.provider ?? t("common.undeclared")} <span className="muted">{p.agents.executor.models.join(", ")}</span></td>
              <td><code className="path" title={p.root}>{p.root}</code></td>
            </tr>)}</tbody>
          </table>
        </div>}
  </>;
}
