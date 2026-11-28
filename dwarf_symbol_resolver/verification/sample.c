/*
 * 左辺値 → アドレス/マスク解決の検証用サンプル
 *   - 単純な変数 (外部結合 / ファイル内 static / 関数内 static)
 *   - 1次元・2次元配列, enum をインデックスに使う配列
 *   - 構造体のネスト, 構造体の配列, ビットフィールド, 共用体
 *   - マクロ (単純, 部分パス + さらに深いパス, 関数形式, ## 連結, 定数式インデックス)
 *
 * コメント形式は2種類を混在させている
 *   形式A: [unit] LSB=... OFS=... 説明
 *   形式B: ///< unit: ..., lsb: ..., ofs: ..., desc: ...
 */

/* ---------- 型 ---------- */

typedef enum {
    CH_A,
    CH_B,
    CH_C,
    CH_NUM
} ChannelId;

typedef struct {
    unsigned int en    : 1;   /* [-] 有効フラグ */
    unsigned int mode  : 3;   /* [-] 動作モード */
    unsigned int level : 12;  /* [%] LSB=100/4096 OFS=0 出力レベル */
    unsigned int       : 0;   /* 次の格納単位へ */
    unsigned char flags : 2;  ///< unit: -, lsb: 1, ofs: 0, desc: 状態フラグ
    unsigned short wide : 10; ///< unit: mV, lsb: 5, ofs: -2560, desc: 電圧
} Bits;

typedef struct {
    short m[6];               /* [Nm] LSB=1/16 OFS=0 トルク */
    Bits  bits;
} Inner;

typedef struct {
    int   id;                 /* [-] 識別子 */
    Inner ar[3];
    union {
        unsigned long u32;    /* [-] 生データ (32bit) */
        unsigned char b[4];   /* [-] 生データ (バイト) */
    } raw;
} Outer;

/* ---------- 変数 ---------- */

volatile int            g_speed;        /* [rpm] LSB=1/(128*1000) OFS=0 エンジン回転数 */
volatile short          g_ar[8];        /* [degC] LSB=0.1 OFS=-40 温度 */
volatile unsigned char  g_mat[3][4];    ///< unit: -, lsb: 1, ofs: 0, desc: 2次元テーブル
volatile Outer          st;
volatile Inner          ch[CH_NUM];

/* ## で名前を組み立てる対象 */
volatile unsigned short g_eng_spd;      /* [rpm] LSB=1 OFS=0 回転数(##) */
volatile short          g_eng_tmp;      /* [degC] LSB=1/2 OFS=-40 水温(##) */
volatile unsigned short g_mot_spd;      /* [rpm] LSB=4 OFS=0 モータ回転数(##) */

/* 内部結合 */
static volatile unsigned short s_count;  /* [count] LSB=1 OFS=0 ファイル内static */
static volatile Inner          s_inner;  /* ファイル内static構造体 */

/* ---------- マクロ ---------- */

/* 単純 */
#define SPEED            g_speed
#define TEMP3            (g_ar[3])

/* 部分パスを定義し, 別マクロでさらに深く参照 */
#define ST_AR1           (st.ar[1])
#define ST_AR1_M4        (ST_AR1.m[4])
#define ST_AR1_BITS      (ST_AR1.bits)
#define ST_AR1_LEVEL     (ST_AR1_BITS.level)
#define ST_AR1_WIDE      (ST_AR1_BITS.wide)

/* 関数形式 */
#define ST_M(i, j)       (st.ar[i].m[j])
#define MAT(r, c)        (g_mat[r][c])

/* 定数式インデックス */
#define IDX_BASE         2
#define AR_AT(o)         (g_ar[IDX_BASE + (o) * 2])

/* ## 連結: 変数名 / enum 名を組み立てる */
#define SIG(dev, name)   (g_##dev##_##name)
#define CH(n)            (ch[CH_##n])
#define CH_M(n, k)       (CH(n).m[k])
#define CH_FLAG(n)       (CH(n).bits.flags)

/* 共用体 */
#define RAW_B2           (st.raw.b[2])

/* 内部結合 */
#define COUNT            s_count
#define S_INNER_MODE     (s_inner.bits.mode)

/* ---------- 関数 ---------- */

static void tick(void)
{
    static volatile unsigned int call_cnt;  /* [count] LSB=1 OFS=0 関数内static */
    call_cnt++;
    COUNT++;
    S_INNER_MODE = 1;
}

void main(void)
{
    for (;;) {
        SPEED++;
        TEMP3 = 1;
        ST_AR1_M4 = 2;
        ST_AR1_LEVEL = 3;
        MAT(1, 2) = 4;
        SIG(eng, spd)++;
        CH_FLAG(B) = 1;
        tick();
    }
}

void _start(void)
{
    main();
}
