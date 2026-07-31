export interface SampleQuestion {
  text: string;
  category: string;
}

export const SAMPLE_QUESTIONS: SampleQuestion[] = [
  {
    text: "列出前 10 部影片的编号和标题",
    category: "基础查询",
  },
  {
    text: "租金收入最高的 10 部电影是哪些？",
    category: "聚合统计",
  },
  {
    text: "按月统计 2007 年的租赁数量趋势",
    category: "趋势分析",
  },
  {
    text: "各电影分类的平均租赁时长对比",
    category: "聚合统计",
  },
  {
    text: "每位客户租了多少部不同的电影？",
    category: "多表关联",
  },
  {
    text: "哪些演员出演过最多的电影？",
    category: "多表关联",
  },
];

export const HELP_SECTIONS: {
  title: string;
  questions: SampleQuestion[];
}[] = [
  {
    title: "基础查询",
    questions: [
      { text: "列出前 10 部影片的编号和标题", category: "基础查询" },
      { text: "列出所有电影分类", category: "基础查询" },
      { text: "有多少个客户？", category: "基础查询" },
    ],
  },
  {
    title: "聚合统计",
    questions: [
      { text: "租金收入最高的 10 部电影是哪些？", category: "聚合统计" },
      { text: "每个电影分类有多少部电影？", category: "聚合统计" },
      { text: "各电影分类的平均租赁时长对比", category: "聚合统计" },
    ],
  },
  {
    title: "趋势分析",
    questions: [
      { text: "按月统计 2007 年的租赁数量趋势", category: "趋势分析" },
    ],
  },
  {
    title: "多表关联",
    questions: [
      { text: "每位客户租了多少部不同的电影？", category: "多表关联" },
      { text: "哪些演员出演过最多的电影？", category: "多表关联" },
    ],
  },
];

export const PAGILA_TABLES: string[] = [
  "actor",
  "address",
  "category",
  "city",
  "country",
  "customer",
  "film",
  "film_actor",
  "film_category",
  "inventory",
  "language",
  "payment",
  "rental",
];
