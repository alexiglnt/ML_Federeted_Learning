/* Algèbre linéaire minimale — juste ce qu'il faut pour les deux moteurs.
 *
 * Les matrices en jeu font 5×5 (quatre variables plus l'ordonnée à l'origine) :
 * une élimination de Gauss avec pivot partiel est largement suffisante et évite
 * d'embarquer une bibliothèque. Aucune dépendance externe, ce qui compte ici :
 * le collègue doit pouvoir ouvrir la page et voir que rien ne part ailleurs.
 */

/** Matrice nulle de taille rows × cols. */
export function zeros(rows, cols) {
  return Array.from({ length: rows }, () => new Float64Array(cols));
}

/** Matrice de conception [1, X] : la colonne de 1 porte l'ordonnée. */
export function designMatrix(X) {
  return X.map((row) => [1, ...row]);
}

/** Produit Aᵗ·A. */
export function gram(A) {
  const n = A.length;
  const p = A[0].length;
  const out = zeros(p, p);
  for (let k = 0; k < n; k++) {
    const row = A[k];
    for (let i = 0; i < p; i++) {
      const vi = row[i];
      for (let j = i; j < p; j++) out[i][j] += vi * row[j];
    }
  }
  for (let i = 0; i < p; i++) for (let j = 0; j < i; j++) out[i][j] = out[j][i];
  return out;
}

/** Produit Aᵗ·y. */
export function matTvec(A, y) {
  const p = A[0].length;
  const out = new Float64Array(p);
  for (let k = 0; k < A.length; k++) {
    const row = A[k];
    for (let i = 0; i < p; i++) out[i] += row[i] * y[k];
  }
  return out;
}

/** Produit scalaire. */
export function dot(a, b) {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}

/**
 * Résout A·x = b par élimination de Gauss avec pivot partiel.
 *
 * Une régularisation de Tikhonov minuscule est ajoutée si la matrice s'avère
 * singulière. Le cas se produit vraiment : il suffit qu'un collègue garde une
 * variable constante dans son plan d'expériences (une seule vitesse de coupe,
 * par exemple) pour que deux colonnes deviennent colinéaires. Mieux vaut une
 * solution stable, accompagnée d'un avertissement dans l'interface, qu'un NaN
 * qui se propage silencieusement jusqu'au score affiché.
 */
export function solve(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);

  for (let col = 0; col < n; col++) {
    let pivot = col;
    for (let r = col + 1; r < n; r++) {
      if (Math.abs(M[r][col]) > Math.abs(M[pivot][col])) pivot = r;
    }
    if (Math.abs(M[pivot][col]) < 1e-12) return null; // singulière
    if (pivot !== col) {
      const tmp = M[pivot];
      M[pivot] = M[col];
      M[col] = tmp;
    }
    const diag = M[col][col];
    for (let r = col + 1; r < n; r++) {
      const factor = M[r][col] / diag;
      if (factor === 0) continue;
      for (let c = col; c <= n; c++) M[r][c] -= factor * M[col][c];
    }
  }

  const x = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let sum = M[r][n];
    for (let c = r + 1; c < n; c++) sum -= M[r][c] * x[c];
    x[r] = sum / M[r][r];
  }
  return x;
}

/**
 * Résolution tolérante : en cas de matrice singulière, ajoute une crête
 * croissante jusqu'à obtenir une solution. La crête retenue est renvoyée pour
 * que l'interface puisse le signaler honnêtement.
 */
export function solveRegularised(A, b) {
  const direct = solve(A, b);
  if (direct) return { x: direct, ridge: 0 };

  const n = b.length;
  let scale = 0;
  for (let i = 0; i < n; i++) scale = Math.max(scale, Math.abs(A[i][i]));
  scale = scale || 1;

  for (const factor of [1e-10, 1e-8, 1e-6, 1e-4, 1e-2]) {
    const ridge = factor * scale;
    const B = A.map((row, i) => row.map((v, j) => (i === j ? v + ridge : v)));
    const x = solve(B, b);
    if (x) return { x, ridge };
  }
  return { x: null, ridge: null };
}
