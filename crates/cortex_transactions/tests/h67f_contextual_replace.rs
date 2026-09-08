use cortex_transactions::TransactionManager;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn fixture(name: &str) -> (PathBuf, PathBuf) {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root =
        std::env::temp_dir().join(format!("cortex-h67f-{name}-{}-{nonce}", std::process::id()));
    let state = root.join(".state");
    fs::create_dir_all(root.join("src")).expect("fixture source");
    fs::create_dir_all(&state).expect("fixture state");
    (root, state)
}

#[test]
fn contextual_line_anchors_recover_a_rustfmt_reflowed_block() {
    let (root, state) = fixture("reflow");
    let path = root.join("src/main.rs");
    fs::write(
        &path,
        "fn render() {\n    let value = compute(\n        1,\n        2,\n    );\n    println!(\"{value}\");\n}\n",
    )
    .expect("fixture file");

    let mut manager = TransactionManager::new(&root, &state).expect("manager");
    manager.begin("h67f-reflow").expect("transaction");
    let replaced = manager
        .replace_text(
            "src/main.rs",
            "fn render() {\n    let value = compute(1, 2);\n    println!(\"{value}\");\n}\n",
            "fn render() {\n    let value = compute(3, 4);\n    println!(\"{value}\");\n}\n",
            1,
        )
        .expect("contextual replacement should recover safely");

    assert_eq!(replaced, 1);
    let current = fs::read_to_string(&path).expect("updated file");
    assert!(current.contains("compute(3, 4)"));
    assert!(!current.contains("compute(\n        1,"));
    let _ = manager.rollback();
    let _ = fs::remove_dir_all(root);
}

#[test]
fn contextual_line_anchors_fail_closed_when_the_region_is_ambiguous() {
    let (root, state) = fixture("ambiguous");
    let path = root.join("src/main.rs");
    fs::write(
        &path,
        "fn render() {\n    one();\n}\n\nfn render() {\n    two();\n}\n",
    )
    .expect("fixture file");

    let mut manager = TransactionManager::new(&root, &state).expect("manager");
    manager.begin("h67f-ambiguous").expect("transaction");
    let error = manager
        .replace_text(
            "src/main.rs",
            "fn render() {\n    stale();\n}\n",
            "fn render() {\n    replacement();\n}\n",
            1,
        )
        .expect_err("ambiguous anchors must fail closed");

    assert!(error.contains("no unique"));
    let current = fs::read_to_string(&path).expect("unchanged file");
    assert!(current.contains("one();"));
    assert!(current.contains("two();"));
    let _ = manager.rollback();
    let _ = fs::remove_dir_all(root);
}
