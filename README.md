Readme.md

# ai-core Readme

A public repository for deterministic verification, core protocol specifications, and general-purpose utilities.
It provides foundational components that complement the non-determinism of LLMs (such as hallucinations, output variance, and context degradation) through external deterministic processing and structured data.

## Overview

This repository provides open components that serve as the foundation for state management, verification, and computation in complex AI workflows and agent coordination.

- **core-verifier**: Foundational modules for deterministic verification and computation.
- **uahp-spec**: Base protocol specifications and schema definitions for inter-agent handoffs and state transitions.

Note: Private and commercial components—such as the 32-bit universal container / 5-layer encapsulation architecture and multi-AI self-healing systems (corresponding to `k-ai-arch32` and `k-ai-Lib`)—are managed separately.

---

## Licensing & Terms of Use

### Non-Commercial Use & Modification
- **Free for non-commercial use** (including personal research, learning, evaluation, and non-commercial projects).
- **Modification for your own environment is allowed**. Feel free to customize it as needed.
- Please retain attribution to this repository and the creator (K) when using, modifying, or redistributing.

### Extensions Based on This Idea
- **Extensions based on this idea are generally permitted**.
- However, please consult with us in advance regarding your intent and design before proceeding with extended/derivative development or public/external release.

### Commercial Use
- **Commercial use (including integration into commercial products, paid services, internal business infrastructure, or other for-profit use) requires prior permission**.
- If you wish to use this commercially, please contact us via the channel below. We will review your use case and requirements and provide information on individual licensing.

---

## Inquiries & Commercial Requests

For extension consultations or commercial licensing requests, please reach out through the following channels:

- **GitHub Issues / Discussions**: Use GitHub for technical questions, non-commercial discussions, and extension consultations.
- **Inquiry**: `[Contact Email Address / Application Form URL]`

### What to Include in Your Inquiry
To help us review your request smoothly, please include the following details:
1. **Purpose & Usage Form** (extension consultation, internal business use, commercial product integration, paid service provision, etc.)
2. **Target System Scale & Model Configuration**
3. **Expected Throughput & Operating Environment**

---

# ai-core（日本語訳）

決定論的検証・プロトコル基本仕様・汎用ユーティリティを扱う公開リポジトリです。
LLMの非決定性（ハルシネーションや出力の揺れ、文脈の劣化）を外部の決定論的処理と構造化データで補完するための基盤コンポーネントを公開しています。

## 概要

本リポジトリでは、複雑なAI処理やエージェント連携における状態管理・検証・計算の土台となる公開コンポーネントを提供します。

- **core-verifier**: 決定論的な検証・計算処理のための基盤モジュール
- **uahp-spec**: エージェント間ハンドオフ・状態遷移の基本プロトコル仕様およびスキーマ定義

※ 32ビット・ユニバーサルコンテナ／5層カプセル化アーキテクチャおよびマルチAIセルフヒーリング等の非公開・商用コンポーネント（`k-ai-arch32` / `k-ai-Lib` 相当）とは分離して管理しています。

---

## ライセンス & 利用条件

### 非商用利用・改変
- **非商用目的であれば自由にご利用いただけます**（個人研究、学習、検証、非商用プロジェクトなど）。
- **ご自身の環境に合わせた改変も自由です**。必要な形にカスタマイズして使ってください。
- 利用・改変・再配布の際は、本リポジトリおよび作成者（K）のクレジット表記を残してください。

### アイデアをベースとした拡張
- **このアイデアをベースに拡張したい場合は基本的に許可します**。
- ただし、拡張・派生開発を進める前（または公開・展開前）に、意図や構成について一度ご相談ください。

### 商用利用
- **商用利用（商用プロダクトへの組み込み、有償サービス・社内業務基盤への適用、その他営利目的の利用）には事前の許諾が必要です**。
- 商用利用をご希望の場合は、下記窓口までご連絡ください。利用形態や要件を確認のうえ、個別許諾についてご案内します。

---

## 相談・商用利用に関するお問い合わせ

拡張の相談や商用利用の許諾申請は、下記窓口よりご連絡ください。

- **GitHub Issues / Discussions**: 技術的な質問や非商用での議論、拡張に関する相談はGitHub上をご利用ください。
- **Inquiry**: `[担当窓口メールアドレス / 申請フォームURL]`

### お問い合わせ時に記載してほしいこと
ご相談や商用利用のご申請の際は、スムーズな確認のために以下の項目をご記載ください。
1. **利用目的・形態**（拡張の相談、自社業務利用、商用製品への組み込み、有償サービス提供など）
2. **対象システム規模・利用モデル構成**
3. **想定スループット・運用環境**


## 背景・小説とのつながり (Story & Background)

本リポジトリの設計思想や軽量化・履歴管理の背景は、小説「軽量化AI」シリーズとも連動しています。
物語の流れや着想の背景から読みたい場合は、以下の作品・解説をご覧ください。

- 関連作品：[『河内のおっさんの次世代推論AIとAGIロードマップ』](https://ncode.syosetu.com/n9756mz/)

## 構成と各モジュールへのリンク

- [履歴インデックス（History Index）](./history/History_Index_jp.md)（[English](./history/History_Index.md)）：チャットの履歴をインデックス化してチャンクを参照し貼るしネーションを改善
- [言語理解（langlib）](./langlib/)：文法分解・ID化・再現差分および判定評価用のプロンプトとスクリプト群
- [計算ライブラリ（mathlib）](./mathlib/mathlib.py)（評価スクリプト：[eval.py](./mathlib/eval.py)）：厳密計算・計算結果の精査・評価ハーネス
