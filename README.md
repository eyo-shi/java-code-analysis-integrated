# Java Code Analysis with Neo4j (Integrated AMP)

Neo4j Kubernetes ランチャーと Java コード解析パイプラインを **1 つの CML AMP** に統合したプロトタイプです。単一 Project (単一 Kubernetes namespace) 内で Neo4j Application と解析 Job を起動するため、Cloudera Sandbox のような cross-namespace 通信が制限された環境でも Internal Bolt がそのまま解決できます。

## この AMP がやること

1. Neo4j Docker イメージを CML Project の Kubernetes namespace に Application として起動 (`1_start-neo4j/`)
2. 指定した Git リポジトリの Java ソースを clone し、Spring MVC + MyBatis を前提とした業務–画面–SQL–テーブル間のグラフを構築 (`code_analysis/parsers/`)
3. 同 namespace の Neo4j に Bolt で ingest (`code_analysis/neo4j_loader.py`)

## クイックスタート (CML)

1. 本 AMP を CML にデプロイ (Install Dependencies が自動実行)
2. **Applications** ページで `Neo4j Launcher` が Running になるのを待つ
3. `Neo4j Launcher` の Application Log を開き、**Internal Bolt URI** と **password** を控える
   例: `bolt://cml-neo4j-10xfi5ukxwfadjsr.mlx-user-98:7687` / `Neo4jPass1234`
4. **Project Settings → Advanced → Environment Variables** で以下を上書き:
   - `NEO4J_URI` = 上記 Internal Bolt URI
   - `NEO4J_PASSWORD` = Application Log のパスワード
   - (必要なら) `GIT_REPO_URL` / `GIT_REF` を解析対象に合わせて変更
5. **Jobs** ページから `Analyze and Ingest` を Run

Job 完了後、`Neo4j Launcher` Application 画面の Browser リンクから Neo4j ブラウザにアクセスし、下の [分析クエリ例](#分析クエリ例) を実行できます。

## ローカル実行

```bash
pip install -r 0_session-install-dependencies/requirements.txt
# cmlbootstrap は Project 環境変数への seed 用途のみ (ローカルでは不要)

export NEO4J_URI=bolt://localhost:7687
export NEO4J_PASSWORD=...
export GIT_REPO_URL=https://github.com/your-org/your-java-app.git
export GIT_REF=main

python3 2_session-analyze-ingest/analyze_ingest.py
```

`SOURCE_PATH` を設定した場合は clone をスキップしてそのディレクトリを解析します。

## 環境変数

Project Settings → Advanced → Environment Variables で設定します (`.project-metadata.yaml` から seed 済み)。

### Neo4j Launcher 用

| 変数 | 既定値 | 用途 |
|------|--------|------|
| `NEO4J_USERNAME` | `neo4j` | Neo4j ユーザー名 |
| `NEO4J_PASSWORD` | (未設定なら `Neo4jPass1234`) | Neo4j パスワード |
| `NEO4J_ACCEPT_LICENSE_AGREEMENT` | `yes` | Neo4j Docker イメージの起動に必須 |
| `NEO4J_SERVICE_TYPE` | `LoadBalancer` | K8s Service 種別 |
| `NEO4J_NODE_PORT_BOLT` / `NEO4J_NODE_PORT_HTTP` | (未設定) | NodePort 使用時 |
| `NEO4J_PLUGINS` | `[]` | Neo4j plugins JSON (`["apoc"]` など) |
| `NEO4J_MEMORY` | `4Gi` | Neo4j Pod のメモリ上限 |
| `NEO4J_USE_PVC` | `false` | Project PVC に永続化するか |

### Analyze and Ingest 用

| 変数 | 既定値 | 用途 |
|------|--------|------|
| `GIT_REPO_URL` | terasoluna サンプル | 解析対象リポジトリ |
| `GIT_REF` | サンプルタグ | ブランチ/タグ |
| `NEO4J_URI` | placeholder | Application Log の Internal Bolt に置換 |
| `CLONE_DIR` | `/tmp/source` | clone 先 |
| `SOURCE_PATH` | `-` | ローカルパス指定 (未使用時 `-`) |
| `PROJECT_ID` | `-` | Neo4j 再投入キー (未指定ならリポ名から生成) |
| `PROJECT_NAME` | `-` | 表示名 (未指定ならリポ名から生成) |
| `EXCLUDE_DIRS` | `.git,target,...` | walk 対象外ディレクトリ |

## グラフノード

| ノード | 説明 | 主な取得元 |
|--------|------|-----------|
| `Business` / `Screen` / `Process` | 業務・画面・プロセス | Controller モジュール + i18n |
| `BusinessConcept` / `DataEntity` | 業務概念・データエンティティ | `domain/model` |
| `Database` / `Table` / `Column` | DB スキーマ | DDL SQL + JDBC 設定 |
| `FormField` | 画面フォーム項目 | `*Form.java` |
| `JavaClass` / `JavaMethod` | Java コード | `.java` |
| `SQL` / `Operation` | DB アクセス | MyBatis `*Repository.xml` |
| `Condition` / `BusinessRule` | バリデーション | `*Form.java` + `*Validator.java` |
| `DesignDocument` / `Evidence` | ドキュメント・根拠 | README 等 |

主要リレーション: `HAS_SCREEN`, `IMPLEMENTED_BY`, `HAS_FIELD`, `BINDS_TO`, `VALIDATES`, `CHECKS`, `WRITES`, `INSERTS`/`UPDATES`/`DELETES`/`SELECTS`, `CONTAINS`, `HAS_COLUMN`。

## 分析クエリ例

### ① 指定 DB のテーブルを更新する業務一覧

```cypher
MATCH (db:Database {logical_name: $dbLogicalName, project_id: $projectId})
      -[:CONTAINS]->(t:Table)
MATCH (q:SQL)-[:WRITES|UPDATES|INSERTS]->(t)
WHERE q.operation IN ['INSERT', 'UPDATE']
MATCH (repo:JavaMethod)-[:EXECUTES]->(q)
MATCH (svc:JavaMethod)-[:CALLS*1..4]->(repo)
MATCH (s:Screen)-[:IMPLEMENTED_BY]->(svc)
MATCH (b:Business)-[:HAS_SCREEN]->(s)
RETURN DISTINCT b.name AS business, s.name AS screen, t.name AS table,
       collect(DISTINCT q.operation) AS operations
ORDER BY business, screen
```

### ② 画面ごとの INSERT/UPDATE カラムとバリデーション条件

```cypher
MATCH (s:Screen {project_id: $projectId})
OPTIONAL MATCH (s)-[:IMPLEMENTED_BY]->(svc:JavaMethod)
      -[:CALLS*1..4]->(repo:JavaMethod)-[:EXECUTES]->(q:SQL)
      -[w:WRITES]->(c:Column)<-[:HAS_COLUMN]-(t:Table)<-[:CONTAINS]-(db:Database)
WHERE w.operation IN ['INSERT', 'UPDATE'] OR q.operation IN ['INSERT', 'UPDATE']
OPTIONAL MATCH (s)-[:VALIDATES]->(cond:Condition)-[:CHECKS]->(c2:Column)
RETURN s.name AS screen, db.logical_name AS database, t.name AS table,
       collect(DISTINCT c.name) AS written_columns,
       collect(DISTINCT {field: cond.field_name, rule: cond.rule_type,
                         constraint: cond.constraint, message: cond.name}) AS conditions
ORDER BY screen, database, table
```

### ③ 同一カラムを更新する画面間のバリデーション差分

```cypher
MATCH (s:Screen {project_id: $projectId})-[:VALIDATES]->(cond:Condition)
      -[:CHECKS]->(c:Column)<-[:HAS_COLUMN]-(t:Table)
MATCH (s2:Screen {project_id: $projectId})-[:IMPLEMENTED_BY]->(:JavaMethod)
      -[:CALLS*1..4]->(:JavaMethod)-[:EXECUTES]->(q:SQL)-[:WRITES]->(c)
WHERE s <> s2 AND q.operation IN ['INSERT', 'UPDATE']
WITH c, t, collect(DISTINCT {screen: s.name, field: cond.field_name,
    rule: cond.rule_type, constraint: cond.constraint, message: cond.name}) AS validations
WHERE size(validations) > 1
RETURN t.name AS table, c.name AS column, validations
ORDER BY table, column
```

## リポジトリ構成

```
0_session-install-dependencies/  # 依存 (kubernetes / neo4j / cmlbootstrap) + project env seed
1_start-neo4j/                    # Neo4j を CML Application として起動
2_session-analyze-ingest/         # 解析 + ingest エントリポイント
code_analysis/                    # 解析パイプライン (parsers / models / neo4j_loader)
utils/                            # neo4j-launcher 共通ユーティリティ
tests/                            # unittest
```

## テスト

```bash
python3 -m unittest discover -s tests -v
```

## 由来

このリポジトリは以下 2 つの CML AMP を統合したものです:

- [neo4j-launcher](https://github.com/eyo-shi/neo4j-launcher) — Neo4j Kubernetes launcher
- [java-code-analysis](https://github.com/eyo-shi/java-code-analysis) — Java 業務コード解析

Sandbox 環境で 2 AMP 間の Bolt 接続がネットワーク境界により成立しないため、両者を単一 AMP に統合しています。詳細は Git ログの初回コミットを参照。

## ライセンス

Apache License 2.0 (`LICENSE` 参照)。同梱コンポーネントの著作権情報は `NOTICES/` 配下を参照してください。
