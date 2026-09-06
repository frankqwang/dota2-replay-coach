
## QuickStart
直接复制github链接，告诉你的ai安装这个skill，然后发比赛id给他，说你要复盘的内容即可。

## skill做了什么
你只需要提供一个比赛id，这个skill里面会根据id去请求opendota api获取v社录像下载链接，拿到链接之后，
有一个parser，可以解析录像协议，拆解出原始的全部游戏事件，几十万级别，
然后你可以让ai挑你关心的，比如团战，占位，击杀，出装什么的随便你问了就，他自己去数据里面挖掘出来


## 关于成本
录像下载、解析出完整游戏事件，都是程序完成，无成本，时间大约花费1-2分钟，一次性动作，生成一份完整游戏事件json，后续对话不会重复解析。
默认会提取关键的一些事件，大概几十K文本，给ai分析，你也可以自己聊天指定想要关注的内容，让ai去原始内容里做数据挖掘分析。
粗略成本如下图：

<img width="500" alt="475650e2a6373173aba6f36b9a7903e5" src="https://github.com/user-attachments/assets/b648c9d0-62ae-4d7b-8a20-a680d46c794f" />


## 效果示例：
<img width="500" alt="aa95edefdbe41ae16fec15c9c61ad1dc" src="https://github.com/user-attachments/assets/c37cb3ac-f992-49c7-b548-147c443192a5" />
<img width="500" alt="832887e041eacc1d6040afdecb02f335" src="https://github.com/user-attachments/assets/c4698e11-528f-479c-a060-175f83bf9582" />
<img width="500" alt="8e6216e11b1fc88958f498f486302059" src="https://github.com/user-attachments/assets/1492ca8e-e047-4002-bdef-522a85853390" />
<img width="500" alt="f1575479596b5e742ad00e350977003b" src="https://github.com/user-attachments/assets/04b676c1-a1bd-44d6-b280-0377a7f200b9" />

